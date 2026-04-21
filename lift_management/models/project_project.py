# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class ProjectProject(models.Model):
    """
    Extends project.project for lift installation projects.
    When the project stage transitions to 'Done', a LiftAsset record is
    automatically created and linked to the originating Sale Order.
    """

    _inherit = 'project.project'

    serial_number = fields.Char(
        string='Lift Serial Number',
        readonly=True,
        default='New',
        copy=False,
        tracking=True,
    )
    site_location = fields.Char(
        string='Site Location',
        related='reinvoiced_sale_order_id.opportunity_id.site_location',
        store=True,
        readonly=True,
    )
    lift_name = fields.Char(string='Lift Name', compute='_compute_lift_attributes', store=True)

    # Technical specs — derived from product variant attributes on the sale line
    lift_type = fields.Char(
        string='Lift Type', compute='_compute_lift_attributes', store=True, tracking=True,
    )
    capacity = fields.Char(
        string='Capacity', compute='_compute_lift_attributes', store=True, tracking=True,
    )
    floors = fields.Char(
        string='Number of Floors', compute='_compute_lift_attributes', store=True, tracking=True,
    )
    speed = fields.Float(
        string='Speed (m/s)', digits=(6, 2),
        compute='_compute_lift_attributes', store=True, tracking=True,
    )

    # ── Computed ───────────────────────────────────────────────────────────────

    # @api.depends('task_ids.sale_line_id.product_id')
    # def _compute_lift_name(self):
    #     for rec in self:
    #         task = rec.task_ids[:1]
    #         rec.lift_name = task.sale_line_id.product_id.name if task and task.sale_line_id else False

    @api.depends('task_ids.sale_line_id.product_id')
    def _compute_lift_attributes(self):
        for rec in self:
            task = rec.task_ids[:1]

            if not task or not task.sale_line_id:
                rec.lift_name = ""
                rec.floors = ""
                rec.capacity = ""
                rec.lift_type = ""
                continue

            product = task.sale_line_id.product_id
            attr_values = product.product_template_variant_value_ids

            def get_val(attr_name):
                match = attr_values.filtered(lambda v: v.attribute_id.name == attr_name)
                return match[0].name if match else False

            rec.lift_name = get_val('Lift Company') or ""
            rec.floors = get_val('Number of Floors') or ""
            rec.capacity = get_val('Capacity') or ""
            rec.lift_type = get_val('Lift Type') or ""
        # ── ORM overrides ──────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('serial_number', 'New') == 'New':
                vals['serial_number'] = (
                    self.env['ir.sequence'].next_by_code('project.lift.serial') or 'New'
                )
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if 'stage_id' in vals:
            for rec in self:
                if rec.stage_id.name.strip().lower() == 'done':
                    rec._create_lift_asset_if_missing()
        return result

    # ── Business logic ─────────────────────────────────────────────────────────

    def _create_lift_asset_if_missing(self):
        """
        Called when a project moves to the Done stage.
        Creates a LiftAsset (if one does not already exist) and links it
        back to the originating Sale Order.
        """
        existing = self.env['lift.asset'].search(
            [('project_id', '=', self.id)], limit=1,
        )
        if existing:
            return existing

        sale_order = self.sale_line_id.order_id if self.sale_line_id else False
        asset = self.env['lift.asset'].create({
            'name': self.lift_name or self.name,
            'serial_number': self.serial_number or '/',
            'customer_id': self.partner_id.id,
            'site_location': self.site_location,
            'installation_date': fields.Date.today(),
            'warranty_expiry': fields.Date.today() + relativedelta(years=1),
            'project_id': self.id,
            'capacity': self.capacity,
            'floors': self.floors,
            'lift_type': self.lift_type,
            'speed': self.speed,
            'sale_order_id': sale_order.id if sale_order else False,
        })

        if sale_order:
            sale_order.lift_asset_id = asset.id

        return asset


# ── Project Task ───────────────────────────────────────────────────────────────

class ProjectTask(models.Model):
    """
    Extends project.task for FSM (Field Service) tasks used in lift maintenance.
    Ensures the current user is always assigned to newly created tasks.
    """

    _inherit = 'project.task'

    lift_asset_id = fields.Many2one('lift.asset', string='Lift Asset', index=True)
    customer_id = fields.Many2one(
        'res.partner',
        related='lift_asset_id.customer_id',
        store=True,
        string='Customer',
    )
    maintenance_request_id = fields.Many2one(
        'maintenance.request', string='Maintenance Request',
    )
    used_product_ids = fields.One2many(
        'fsm.product.line', 'task_id', string='Used Products',
    )

    # ── ORM ────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        uid = self.env.uid
        for vals in vals_list:
            raw = vals.get('user_ids')
            current_ids = self._extract_user_ids(raw)
            if uid not in current_ids:
                current_ids.add(uid)
            vals['user_ids'] = [(6, 0, list(current_ids))]
        return super().create(vals_list)

    def write(self, vals):
        if 'user_ids' in vals:
            uid = self.env.uid
            commands = vals['user_ids']
            # Guard: other modules may pass False/None instead of a command list
            if not isinstance(commands, list):
                return super().write(vals)
            # Ensure current user stays assigned
            has_uid = any(
                (isinstance(cmd, (list, tuple)) and cmd[0] == 4 and cmd[1] == uid)
                or (isinstance(cmd, (list, tuple)) and cmd[0] == 6 and uid in (cmd[2] or []))
                for cmd in commands
            )
            if not has_uid:
                vals['user_ids'].append((4, uid))
        return super().write(vals)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_user_ids(commands, base=None):
        """
        Resolve an ORM command list to a plain set of user IDs.
        Safely handles None, False, or any non-list value from external callers.
        """
        ids = set(base or [])
        if not isinstance(commands, (list, tuple)):
            return ids
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                continue
            if cmd[0] == 6:
                ids = set(cmd[2] or [])
            elif cmd[0] == 4:
                ids.add(cmd[1])
            elif cmd[0] in (2, 3):
                ids.discard(cmd[1])
            elif cmd[0] == 5:
                ids.clear()
        return ids


# ── FSM Product Line ───────────────────────────────────────────────────────────

class FSMProductLine(models.Model):
    """
    Tracks parts / products consumed during a field service task.
    """

    _name = 'fsm.product.line'
    _description = 'FSM Product Line'

    task_id = fields.Many2one('project.task', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, string='Product')
    quantity = fields.Float(string='Quantity', default=1.0, digits=(12, 2))
    uom_id = fields.Many2one(
        'uom.uom', string='Unit',
        related='product_id.uom_id', readonly=True,
    )
    price_unit = fields.Float(
        string='Unit Price',
        related='product_id.lst_price', readonly=True,
    )
