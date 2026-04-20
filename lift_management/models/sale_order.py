# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    """
    Extends sale.order with lift-related fields.

    Design decision: the SO contains ONE main lift product line.
    All cost detail (freight, customs, overheads, margin) lives in the
    linked lift.costing sheet — visible via a smart button — keeping
    the SO clean for the customer while preserving full internal visibility.
    """

    _inherit = 'sale.order'

    lift_asset_id = fields.Many2one(
        'lift.asset', string='Lift Asset', readonly=True,
    )
    delivery_time = fields.Date(string='Expected Delivery Date')

    # ── Costing sheet ──────────────────────────────────────────────────────────
    lift_costing_id = fields.Many2one(
        'lift.costing', string='Costing Sheet',
        copy=False,
    )
    lift_costing_count = fields.Integer(compute='_compute_lift_costing_count')

    # ── Lift asset smart button ────────────────────────────────────────────────
    lift_asset_count = fields.Integer(compute='_compute_lift_asset_count')

    # ── Computes ───────────────────────────────────────────────────────────────

    @api.depends('lift_asset_id')
    def _compute_lift_asset_count(self):
        for rec in self:
            rec.lift_asset_count = 1 if rec.lift_asset_id else 0

    @api.depends('lift_costing_id')
    def _compute_lift_costing_count(self):
        for rec in self:
            rec.lift_costing_count = 1 if rec.lift_costing_id else 0

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_view_lift_asset(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lift Asset',
            'res_model': 'lift.asset',
            'view_mode': 'form',
            'res_id': self.lift_asset_id.id,
        }

    def action_open_costing_sheet(self):
        """
        Open the linked costing sheet, or create a new one pre-filled
        with data from this sale order.
        """
        self.ensure_one()

        if self.lift_costing_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Costing Sheet',
                'res_model': 'lift.costing',
                'view_mode': 'form',
                'res_id': self.lift_costing_id.id,
                'target': 'current',
            }

        # Auto-detect the first product line as the main lift product
        main_line = self.order_line[:1]
        costing = self.env['lift.costing'].create({
            'name': self.name,
            'sale_order_id': self.id,
            'opportunity_id': self.opportunity_id.id if self.opportunity_id else False,
            'product_id': main_line.product_id.id if main_line else False,
            'currency_id': self.currency_id.id,
        })
        self.lift_costing_id = costing.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'Costing Sheet',
            'res_model': 'lift.costing',
            'view_mode': 'form',
            'res_id': costing.id,
            'target': 'current',
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    lift_costing_line = fields.Boolean(
        default=False,
        help='Marks this line as auto-generated from a lift costing sheet.',
    )