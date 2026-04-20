# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LiftCosting(models.Model):
    """
    Internal costing sheet for a lift installation.

    Linked to both a CRM opportunity (pre-sale) and a Sale Order (post-quotation).
    The SO carries only the final sale price; this sheet holds the full
    cost breakdown visible to managers only.
    """

    _name = 'lift.costing'
    _description = 'Lift Costing Sheet'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Reference', required=True, tracking=True)

    # ── Links ──────────────────────────────────────────────────────────────────
    opportunity_id = fields.Many2one(
        'crm.lead', string='Opportunity', tracking=True, index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', tracking=True, index=True,
        copy=False,
    )
    product_id = fields.Many2one(
        'product.product', string='Lift Product',
        domain=[('type', 'in', ['product', 'consu'])],
    )

    # ── Currency ───────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # ── Cost components ────────────────────────────────────────────────────────
    supplier_cost = fields.Monetary(string='Supplier Cost',      currency_field='currency_id')
    freight_cost  = fields.Monetary(string='Freight Cost',       currency_field='currency_id')
    customs_cost  = fields.Monetary(string='Customs / Duties',   currency_field='currency_id')
    installation_cost = fields.Monetary(string='Installation Cost', currency_field='currency_id')
    material_cost = fields.Monetary(string='Material Cost',      currency_field='currency_id')
    overhead_cost = fields.Monetary(string='Overhead Cost',      currency_field='currency_id')

    margin_percent = fields.Float(string='Margin (%)', digits=(5, 2), default=20.0)

    # ── Computed totals ────────────────────────────────────────────────────────
    total_cost = fields.Monetary(
        string='Total Cost',
        compute='_compute_totals', store=True,
        currency_field='currency_id',
    )
    sale_price = fields.Monetary(
        string='Proposed Sale Price',
        compute='_compute_totals', store=True,
        currency_field='currency_id',
    )

    @api.depends(
        'supplier_cost', 'freight_cost', 'customs_cost',
        'installation_cost', 'material_cost', 'overhead_cost', 'margin_percent',
    )
    def _compute_totals(self):
        for rec in self:
            total = (
                rec.supplier_cost
                + rec.freight_cost
                + rec.customs_cost
                + rec.installation_cost
                + rec.material_cost
                + rec.overhead_cost
            )
            rec.total_cost = total
            rec.sale_price = total * (1 + rec.margin_percent / 100.0)

    # ── Action: push sale_price to the SO product line ─────────────────────────
    def action_apply_price_to_order(self):
        """
        Creates/updates a dedicated SO line for the lift costing total.
        Uses a sentinel product 'Lift Installation (Costing)' to identify the line.
        """
        self.ensure_one()
        if not self.sale_order_id:
            return

        # Get or create a generic service product to represent the costing total
        costing_product = self.env.ref(
            'lift_management.product_lift_costing_total',
            raise_if_not_found=False,
        )
        if not costing_product:
            costing_product = self.env['product.product'].search([
                ('default_code', '=', 'LIFT-COST-TOTAL')
            ], limit=1)

        if not costing_product:
            raise UserError(
                'Costing summary product not found. '
                'Please ensure product with internal reference LIFT-COST-TOTAL exists.'
            )

        order = self.sale_order_id

        # Find an existing costing line on the SO (if already applied before)
        existing_line = order.order_line.filtered(
            lambda l: l.lift_costing_line is True
        )[:1]

        line_vals = {
            'order_id': order.id,
            'product_id': costing_product.id,
            'name': f'Lift Installation – {self.name}',
            'product_uom_qty': 1,
            'price_unit': self.sale_price,
            'lift_costing_line': True,
        }

        if existing_line:
            existing_line.write({
                'name': line_vals['name'],
                'price_unit': self.sale_price,
            })
        else:
            self.env['sale.order.line'].create(line_vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Total Cost Applied',
                'message': f'{self.sale_price:,.2f} added to current order {order.name}.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_print_cost_report(self):
        self.ensure_one()
        return self.env.ref('lift_management.action_report_lift_costing').report_action(self)
