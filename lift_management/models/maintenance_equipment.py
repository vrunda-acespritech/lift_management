# -*- coding: utf-8 -*-
from odoo import fields, models


class MaintenanceEquipment(models.Model):
    """
    Links a standard maintenance.equipment record back to its lift asset.
    Created automatically when a LiftAsset is created.
    """

    _inherit = 'maintenance.equipment'

    lift_asset_id = fields.Many2one(
        'lift.asset',
        string='Lift Asset',
        tracking=True,
        ondelete='set null',
        index=True,
    )
