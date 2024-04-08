"""Web forms used by the dashboard.

Forms are defined using the
` Flask-WTForms <https://wtforms.readthedocs.io/en/latest/>`_ extension. This
allows us to create HTML forms in python without having to worry writing HTML
or avoiding CSRF vulnerabilities.
"""

from flask_wtf import FlaskForm
from wtforms import (SelectMultipleField, HiddenField, TextAreaField,
                     StringField)
from wtforms.validators import DataRequired


class SelectMetricsForm(FlaskForm):
    """Choose metrics from the database.

    This form needs to be updated when we fix our QC metric integrations.
    """
    study_vals = []
    site_vals = []
    session_vals = []
    scan_vals = []
    scantype_vals = []
    metrictype_vals = []

    study_id = SelectMultipleField('Study', coerce=int)
    site_id = SelectMultipleField('Site', coerce=int)
    session_id = SelectMultipleField('Session', coerce=int)
    scan_id = SelectMultipleField('Scan', coerce=int)
    scantype_id = SelectMultipleField('Scan type', coerce=int)
    metrictype_id = SelectMultipleField('Metric type', coerce=int)
    query_complete = HiddenField(default=False)
    is_phantom = HiddenField(default=False)

    def __init__(self, *args, **kwargs):
        FlaskForm.__init__(self, *args, **kwargs)


class StudyOverviewForm(FlaskForm):
    """Make edits to a study's README form.
    """
    readme_txt = TextAreaField('README', id='readme_editor')
    study_id = HiddenField()


class AnalysisForm(FlaskForm):
    """Add a new analysis to the dashboard.

    This feature has not yet been fully implemented.
    """
    name = StringField('Brief name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    software = TextAreaField('Software')
