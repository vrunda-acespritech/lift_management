# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

import base64
import io

import uuid

from reportlab.pdfgen import canvas

from odoo.exceptions import UserError

from reportlab.pdfgen import canvas

from reportlab.lib.pagesizes import A4



class LiftAsset(models.Model):
    """
    Represents a physical lift unit that has been installed at a customer site.
    Created automatically when an installation project reaches the 'Done' stage.
    """

    _name = 'lift.asset'
    _description = 'Lift Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Lift Name', required=True, tracking=True)
    serial_number = fields.Char(
        string='Serial Number', required=True, tracking=True, index=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer', tracking=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    site_location = fields.Char(string='Site Location', tracking=True)

    # ── Related records ────────────────────────────────────────────────────────
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', tracking=True, index=True,
    )
    project_id = fields.Many2one(
        'project.project', string='Installation Project', tracking=True,
    )
    equipment_id = fields.Many2one(
        'maintenance.equipment', string='Maintenance Equipment', readonly=True,
    )

    # ── Technical specs ────────────────────────────────────────────────────────
    lift_type = fields.Char(string='Lift Type', tracking=True)
    capacity = fields.Char(string='Capacity', tracking=True)
    floors = fields.Char(string='Number of Floors', tracking=True)
    speed = fields.Float(string='Speed (m/s)', digits=(6, 2), tracking=True)

    # ── Warranty ───────────────────────────────────────────────────────────────
    installation_date = fields.Date(string='Installation Date', tracking=True)
    warranty_expiry = fields.Date(string='Warranty Expiry', tracking=True)
    warranty_status = fields.Selection(
        selection=[
            ('valid', 'Valid'),
            ('expiring_soon', 'Expiring Soon'),
            ('expired', 'Expired'),
        ],
        string='Warranty Status',
        compute='_compute_warranty_status',
        store=True,
        tracking=True,
    )

    # ── Maintenance ────────────────────────────────────────────────────────────
    maintenance_request_ids = fields.One2many(
        'maintenance.request', 'lift_asset_id', string='Maintenance Requests',
    )
    maintenance_request_count = fields.Integer(
        compute='_compute_maintenance_count', string='Maintenance Count',
    )

    # ── Compute / depends ─────────────────────────────────────────────────────

    @api.depends('warranty_expiry')
    def _compute_warranty_status(self):
        today = date.today()
        soon_threshold = today + relativedelta(days=30)
        for rec in self:
            if not rec.warranty_expiry:
                rec.warranty_status = False
            elif rec.warranty_expiry < today:
                rec.warranty_status = 'expired'
            elif rec.warranty_expiry <= soon_threshold:
                rec.warranty_status = 'expiring_soon'
            else:
                rec.warranty_status = 'valid'

    @api.depends('maintenance_request_ids')
    def _compute_maintenance_count(self):
        # Use read_group for performance instead of len()
        data = self.env['maintenance.request'].read_group(
            domain=[('lift_asset_id', 'in', self.ids)],
            fields=['lift_asset_id'],
            groupby=['lift_asset_id'],
        )
        counts = {row['lift_asset_id'][0]: row['lift_asset_id_count'] for row in data}
        for rec in self:
            rec.maintenance_request_count = counts.get(rec.id, 0)

    # ── Name get ───────────────────────────────────────────────────────────────

    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.sale_order_id:
                parts.append(rec.sale_order_id.name)
            parts.append(rec.name or '')
            label = ' - '.join(filter(None, parts))
            if rec.serial_number:
                label = f'{label} ({rec.serial_number})'
            rec.display_name = label

    # ── ORM overrides ──────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._create_maintenance_equipment()
        return records

    def _create_maintenance_equipment(self):
        """
        Auto-create a maintenance.equipment and an initial preventive
        maintenance.request for every newly created lift asset.
        """
        category = self.env['maintenance.equipment.category'].search([], limit=1)
        for record in self:
            equipment = self.env['maintenance.equipment'].create({
                'name': record.name,
                'lift_asset_id': record.id,
                'category_id': category.id if category else False,
            })
            record.equipment_id = equipment.id

            self.env['maintenance.request'].with_context(
                _lift_asset_skip_fsm=True,   # flag so maintenance_request.create
            ).create({                        # does not loop back here
                'name': f'Initial Service – {record.name}',
                'equipment_id': equipment.id,
                'lift_asset_id': record.id,
                'request_date': fields.Date.today(),
                'maintenance_type': 'preventive',
                'recurring_maintenance': True,
                'repeat_interval': 120,
                'repeat_unit': 'day',
                'repeat_type': 'until',
                'repeat_until': record.warranty_expiry,
                'user_id': record.project_id.user_id.id if record.project_id else False,
            })

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_view_maintenance_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Maintenance Requests',
            'res_model': 'maintenance.request',
            'view_mode': 'list,form',
            'domain': [('lift_asset_id', '=', self.id)],
            'context': {
                'default_lift_asset_id': self.id,
                'default_equipment_id': self.equipment_id.id,
            },
        }

    def action_view_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Order',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }

    # ── Cron ───────────────────────────────────────────────────────────────────

    @api.model
    def cron_check_warranty_expiry(self):
        """
        Runs daily.
        - Recomputes warranty_status (already done via stored compute, but
          a direct search is cheaper than forcing recompute on all records).
        - Sends reminder e-mails at 30, 7, 5 and 3 days before expiry.
        """
        today = date.today()
        reminder_days = {30, 7, 5, 3}
        template = self.env.ref(
            'lift_management.email_template_warranty_reminder', raise_if_not_found=False,
        )

        assets = self.search([('warranty_expiry', '!=', False)])
        for rec in assets:
            days_left = (rec.warranty_expiry - today).days
            if template and days_left in reminder_days and rec.customer_id.email:
                template.send_mail(
                    rec.id,
                    force_send=True,
                    email_values={
                        'email_to': rec.customer_id.email,
                        'email_from': rec.company_id.email or self.env.user.email,
                    },
                )


    def action_create_sign_request(self):
        self.ensure_one()

        report = self.env.ref('lift_management.report_lift_contract_action01')
        pdf_content, _ = report._render_qweb_pdf(report.id, [self.id])

        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}_Contract.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        doc = self.env['documents.document'].create({
            'name': attachment.name,
            'attachment_id': attachment.id,
            'owner_id': self.env.user.id,
        })

        template = self.env['sign.template'].create({
            'name': f'Contract - {self.name}',
        })

        sign_document = self.env['sign.document'].create({
            'template_id': template.id,
            'attachment_id': attachment.id,
        })

        role = self.env['sign.item.role'].search([('name', '=', 'Customer')], limit=1)
        if not role:
            role = self.env['sign.item.role'].create({'name': 'Customer'})

        s_item = self.env['sign.item'].create({
            'template_id': template.id,
            'document_id': sign_document.id,
            'type_id': self.env.ref('sign.sign_item_type_signature').id,
            'required': True,
            'responsible_id': role.id,
            'page': 1,
            'posX': 0.5,
            'posY': 0.2,
            'width': 0.3,
            'height': 0.05,
        })

        sign_request = self.env['sign.request'].create({
            'template_id': template.id,
            'reference': f'Sign Request - {self.name}',
            'lift_asset_id': self.id,
            'request_item_ids': [(0, 0, {
                'partner_id': self.customer_id.id,
                'role_id': role.id,
                
            })]
        })
        def _default_access_token(self):
            print(str(uuid.uuid4()))

        res = {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'view_mode': 'form',
            'res_id': sign_request.id,
            'target': 'current',
        }
        return res 
        
    sign_request_count = fields.Integer(
            compute="_compute_sign_request_count",
            string="Sign Requests")

    def _compute_sign_request_count(self):
                for rec in self:
                    rec.sign_request_count = self.env['sign.request'].search_count([
                        ('lift_asset_id', '=', rec.id)
                    ])

    def action_view_sign_requests(self):
                self.ensure_one()
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Sign Requests',
                    'res_model': 'sign.request',
                    'view_mode': 'list,form',
                    'domain': [('lift_asset_id', '=', self.id)],
                    'context': {
                        'default_lift_asset_id': self.id
                    }
                }
                
        
    class SignRequest(models.Model):
        _inherit = 'sign.request'

        lift_asset_id = fields.Many2one('lift.asset', string="Lift Asset")
        
            
        def _prepare_request_values(self):
            vals = super()._prepare_request_values()
            vals['lift_asset_id'] = self.lift_asset_id.id
            return vals