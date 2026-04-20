# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

try:
    from odoo.http import request as http_request
except ImportError:
    http_request = None


class CrmLead(models.Model):
    """
    Extends crm.lead with lift-specific fields.

    Flow:
      1.  Sales rep creates a lead, marks project_type.
      2a. Installation → site_visit → Survey → Quotation → SO → Project → LiftAsset.
      2b. Service      → lift_asset_id → Maintenance Request (corrective)
                                       or FSM Task (no asset known yet).
    """

    _inherit = 'crm.lead'

    project_type = fields.Selection(
        selection=[('installation', 'Installation'), ('service', 'Service')],
        string='Project Type',
        required=True,
        tracking=True,
    )
    number_of_lifts = fields.Integer(string='Number of Lifts', default=1)
    site_location = fields.Char(string='Site Location', tracking=True)
    site_visit = fields.Boolean(string='Site Visit', tracking=True)

    survey_id = fields.Many2one('survey.survey', string='Survey Template')
    survey_input_ids = fields.One2many(
        'survey.user_input', 'lead_id', string='Survey Submissions',
    )

    # Only visible / relevant for service-type leads
    lift_asset_id = fields.Many2one(
        'lift.asset', string='Existing Lift Asset',
        domain="[('sale_order_id', '!=', False), ('customer_id', '=', partner_id)]",
    )

    # ── Computed helpers ───────────────────────────────────────────────────────

    survey_done = fields.Boolean(compute='_compute_survey_done', store=False)

    @api.depends('survey_input_ids.state')
    def _compute_survey_done(self):
        for rec in self:
            rec.survey_done = any(s.state == 'done' for s in rec.survey_input_ids)

    # ── Onchange ───────────────────────────────────────────────────────────────

    @api.onchange('project_type', 'partner_id')
    def _onchange_project_type_partner(self):
        """Keep lift_asset domain in sync with partner and project_type."""
        if self.project_type != 'service':
            self.lift_asset_id = False

    # ── Button actions ─────────────────────────────────────────────────────────

    def action_open_survey(self):
        """Open the linked survey in a new tab, pre-filling lead_id in the URL."""
        self.ensure_one()
        if not self.survey_id:
            raise ValidationError('Please link a survey template to this lead first.')
        if self.survey_done:
            raise ValidationError('A completed survey already exists for this lead.')
        return {
            'type': 'ir.actions.act_url',
            'url': f'{self.survey_id.get_start_url()}?lead_id={self.id}',
            'target': 'new',
        }

    def action_view_all_submissions(self):
        self.ensure_one()
        return {
            'name': 'Survey Submissions',
            'type': 'ir.actions.act_window',
            'res_model': 'survey.user_input',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'create': False},
        }

    # ── Overridden quotation action ────────────────────────────────────────────

    def action_sale_quotations_new(self):
        """
        Guard rules before creating a quotation:
          - Service lead  → skip to Maintenance Request or FSM Task.
          - Installation  → enforce site_visit + completed survey.
        """
        for lead in self:
            if lead.project_type == 'service':
                return lead._action_service_flow()

            # ── Installation checks ────────────────────────────────────────────
            if not lead.site_visit:
                raise ValidationError(
                    f'({lead.name}) Please mark the site visit as done before '
                    'creating a quotation.'
                )
            if not lead.survey_done:
                raise ValidationError(
                    f'({lead.name}) Please complete the survey before creating a '
                    'quotation.'
                )

        return super().action_sale_quotations_new()

    def _action_service_flow(self):
        """
        For service-type leads:
          - Asset known   → create a corrective Maintenance Request.
          - Asset unknown → create an FSM Task for site investigation.
        """
        self.ensure_one()
        if self.lift_asset_id:
            req = self.env['maintenance.request'].create({
                'name': self.name,
                'lift_asset_id': self.lift_asset_id.id,
                'equipment_id': self.lift_asset_id.equipment_id.id,
                'maintenance_type': 'corrective',
            })
            return {
                'type': 'ir.actions.act_window',
                'name': 'Maintenance Request',
                'res_model': 'maintenance.request',
                'view_mode': 'form',
                'res_id': req.id,
            }

        # Asset not yet identified — open an FSM task
        task = self.env['project.task'].create({
            'name': self.name,
            'is_fsm': True,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Field Task',
            'res_model': 'project.task',
            'view_mode': 'form',
            'res_id': task.id,
        }


class SurveyUserInput(models.Model):
    """
    Extends survey.user_input to capture which CRM lead triggered the survey.
    The lead_id is injected from the URL query string (?lead_id=…).
    """

    _inherit = 'survey.user_input'

    lead_id = fields.Many2one('crm.lead', string='Lead', index=True, ondelete='set null')

    @api.model_create_multi
    def create(self, vals_list):
        # Attempt to pick up lead_id from the HTTP request context (survey start URL).
        lead_id = None
        try:
            if http_request:
                raw = http_request.params.get('lead_id')
                lead_id = int(raw) if raw else None
        except RuntimeError:
            pass  # No active HTTP request (e.g. shell / cron context)

        if lead_id:
            for vals in vals_list:
                vals.setdefault('lead_id', lead_id)

        return super().create(vals_list)
