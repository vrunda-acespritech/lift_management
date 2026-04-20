# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MaintenanceRequest(models.Model):
    """
    Extends maintenance.request with lift-specific fields.

    On creation an FSM task is automatically created — unless the request
    was itself triggered from a LiftAsset creation (flag: _lift_asset_skip_fsm).
    This prevents a create → create recursion loop.
    """

    _inherit = 'maintenance.request'

    lift_asset_id = fields.Many2one(
        'lift.asset', string='Lift Asset', tracking=True, index=True,
    )
    fsm_task_id = fields.Many2one('project.task', string='Field Task', readonly=True)

    # ── Onchange ───────────────────────────────────────────────────────────────

    @api.onchange('lift_asset_id')
    def _onchange_lift_asset(self):
        """When a lift asset is selected, restrict the equipment dropdown."""
        domain = {}
        if self.lift_asset_id:
            self.equipment_id = self.lift_asset_id.equipment_id
            domain['equipment_id'] = [('lift_asset_id', '=', self.lift_asset_id.id)]
        return {'domain': domain}

    # ── ORM ────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        # Auto-populate lift_asset_id from equipment when not provided
        for vals in vals_list:
            if vals.get('equipment_id') and not vals.get('lift_asset_id'):
                equipment = self.env['maintenance.equipment'].browse(vals['equipment_id'])
                if equipment.lift_asset_id:
                    vals['lift_asset_id'] = equipment.lift_asset_id.id

        records = super().create(vals_list)

        # Skip FSM task creation when called from LiftAsset._create_maintenance_equipment
        if not self.env.context.get('_lift_asset_skip_fsm'):
            records._create_fsm_task()

        return records

    # ── Business logic ─────────────────────────────────────────────────────────

    def _create_fsm_task(self):
        """Create an FSM task for each request that does not yet have one."""
        for rec in self:
            if rec.fsm_task_id:
                continue
            task = self._build_fsm_task(rec)
            rec.fsm_task_id = task.id

    def _build_fsm_task(self, rec):
        project = rec.lift_asset_id.project_id if rec.lift_asset_id else False
        if project and not project.allow_timesheets:
            project.allow_timesheets = True
        return self.env['project.task'].create({
            'name': rec.name,
            'is_fsm': True,
            'project_id': project.id if project else False,
            'description': rec.description,
            'user_ids': [(6, 0, [rec.user_id.id])] if rec.user_id else False,
            'maintenance_request_id': rec.id,
            'lift_asset_id': rec.lift_asset_id.id if rec.lift_asset_id else False,
        })

    # ── Button actions ─────────────────────────────────────────────────────────

    def action_create_or_view_fsm_task(self):
        """
        Single smart button: opens the existing task or creates one on demand.
        """
        self.ensure_one()
        if not self.fsm_task_id:
            task = self._build_fsm_task(self)
            self.fsm_task_id = task.id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Field Task',
            'res_model': 'project.task',
            'view_mode': 'form',
            'res_id': self.fsm_task_id.id,
        }
