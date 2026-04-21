# -*- coding: utf-8 -*-
{
    'name': 'Lift Management',
    'version': '19.0.1',
    'summary': 'End-to-end lift installation, asset tracking, and maintenance management.',
    'description': """
Lift Management
===============
Covers the full lifecycle:
  CRM Lead → Survey → Quotation → Installation Project → Lift Asset → Maintenance
    """,
    'category': 'Field Service',
    'sequence': 4,
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'contacts',
        'crm',
        'sale_crm',
        'sale_management',
        'sale_project',
        'project',
        'industry_fsm',
        'hr_timesheet',
        'maintenance',
        'stock',
        'mrp',
        'survey','sign',
    ],
    'data': [
        'demo/project_template.xml',
        'demo/product_attribute.xml',
        'demo/project_task_stages.xml',
        'demo/lift_survey_demo.xml',
        
        # Security — always first
        'security/lift_groups.xml',
        'security/ir.model.access.csv',

        # Master data
        'data/ir_sequence.xml',
        'data/email_template.xml',
        'data/cron.xml',
        'data/lift_contract_template.xml',
        'data/lift_contract_report.xml',

        # Views
        'views/lift_asset_views.xml',
        'views/lift_costing_views.xml',
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
        'views/project_project_views.xml',
        'views/maintenance_request_views.xml',
        'views/lift_menus_views.xml',
        'report/lift_costing_report.xml'
    ],
    'installable': True,
    'application': True,
}
