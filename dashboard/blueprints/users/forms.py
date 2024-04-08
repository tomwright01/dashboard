from flask_wtf import FlaskForm

from wtforms import (SubmitField, HiddenField, StringField, FormField,
                     BooleanField, FieldList, RadioField, SelectMultipleField,
                     EmailField, TelField)
from wtforms.validators import DataRequired


class UserForm(FlaskForm):
    id = HiddenField()
    first_name = StringField('First Name: ',
                           validators=[DataRequired()],
                           render_kw={
                               'required': True,
                               'maxlength': '64',
                               'placeholder': 'Jane'
                           })
    last_name = StringField('Last Name: ',
                          validators=[DataRequired()],
                          render_kw={
                              'required': True,
                              'maxlength': '64',
                              'placeholder': 'Doe'
                          })
    email = EmailField('Email: ',
                       validators=[DataRequired()],
                       render_kw={
                           'required': True,
                           'maxlength': '256',
                           'placeholder': 'Enter email'
                       })
    provider = RadioField('Account provider: ',
                          validators=[DataRequired()],
                          choices=[('github', 'GitHub')],
                          default='github')
    account = StringField('Username: ',
                        validators=[DataRequired()],
                        render_kw={
                            'required':
                            True,
                            'maxlength':
                            '64',
                            'placeholder':
                            'Username used on account ' + 'provider\'s site'
                        })
    position = StringField('Position: ',
                         render_kw={
                             'maxlength': '64',
                             'placeholder': 'Job title or position'
                         })
    institution = StringField('Institution: ',
                            render_kw={
                                'maxlength':
                                '128',
                                'placeholder':
                                'Full name or acronym ' + 'for institution'
                            })
    phone = TelField('Phone Number: ',
                     render_kw={
                         'maxlength': '20',
                         'placeholder': '555-555-5555'
                     })
    ext = StringField('Extension: ',
                    render_kw={
                        'maxlength': '10',
                        'placeholder': 'XXXXXXXXXX'
                    })
    alt_phone = TelField('Alt. Phone Number: ',
                         render_kw={
                             'maxlength': '20',
                             'placeholder': '555-555-5555'
                         })
    alt_ext = StringField('Alt. Extension: ',
                        render_kw={
                            'maxlength': '10',
                            'placeholder': 'XXXXXXXXXX'
                        })
    submit = SubmitField('Save Changes')


class PermissionRadioField(RadioField):
    def __init__(self, *args, **kwargs):
        super(PermissionRadioField, self).__init__(**kwargs)
        # These boolean values need to be represented as strings
        #       1. To display correctly in all browsers
        #       2. To actually update correctly when part of a nested form
        # Change data types at your own risk
        self.choices = [('False', 'Disabled'), ('True', 'Enabled')]
        self.default = 'False'

    def populate_obj(self, obj, name):
        """
        This overrides the default function from wtforms.core.Field to
        ensure the database models receive boolean values and not strings of
        booleans
        """
        if self.data.lower() == 'true':
            data = True
        else:
            data = False
        setattr(obj, name, data)


class StudyPermissionsForm(FlaskForm):
    study_id = HiddenField()
    user_id = HiddenField()
    site_id = HiddenField()
    is_admin = PermissionRadioField('Study Admin')
    primary_contact = PermissionRadioField('Primary Contact')
    kimel_contact = PermissionRadioField('Kimel Contact')
    study_RA = PermissionRadioField('Study RA')
    does_qc = PermissionRadioField('Does QC')
    revoke_access = SubmitField('Remove')


class UserAdminForm(UserForm):
    dashboard_admin = BooleanField('Dashboard Admin: ')
    is_active = BooleanField('Active Account: ')
    studies = FieldList(FormField(StudyPermissionsForm))
    add_access = SelectMultipleField('Enable user access: ')
    update_access = SubmitField(label='Enable')
    revoke_all_access = SubmitField(label='Remove All')

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        """
        This is identical to WTForm 2.1's implementation of 'process',
        but it must pass in the User.studies.values() when it's called with
        an object instead of just User.studies, since studies is a mapped
        collection
        """
        formdata = self.meta.wrap_formdata(self, formdata)

        if data is not None:
            # XXX we want to eventually process 'data' as a new entity.
            #     Temporarily, this can simply be merged with kwargs.
            kwargs = dict(data, **kwargs)

        for name, field, in self._fields.items():
            if obj is not None and hasattr(obj, name):
                # This if statement is the only change made to the original
                # code for BaseForm.process() - Dawn
                if name == 'studies':
                    access_rights = []
                    for study in obj.studies:
                        access_rights.extend(obj.studies[study])
                    field.process(formdata, access_rights)
                else:
                    field.process(formdata, getattr(obj, name))
            elif name in kwargs:
                field.process(formdata, kwargs[name])
            else:
                field.process(formdata)

    def populate_obj(self, obj):
        """
        As with process, this implementation is the same as WTForm 2.1's
        default with the 'studies' field treated as a special case to
        account for the fact that it is a mapped collection
        """
        for name, field in self._fields.items():
            if name == 'studies':
                for study_form in self.studies.entries:
                    if study_form.site_id.data == '':
                        study_form.site_id.data = None
                    match = [su for su in obj.studies[study_form.study_id.data]
                             if study_form.site_id.data == su.site_id]
                    study_form.form.populate_obj(match[0])
            else:
                field.populate_obj(obj, name)


class AccessRequestForm(UserForm):
    studies = FieldList(FormField(StudyPermissionsForm))
    request_access = SelectMultipleField('Request access to studies: ')
    send_request = SubmitField(label='Submit Request')
