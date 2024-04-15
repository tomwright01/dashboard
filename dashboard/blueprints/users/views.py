from flask import session as flask_session
from flask import render_template, flash, url_for, redirect, request
from flask_login import logout_user, current_user, login_required

from dashboard import lm
from . import user_bp
from .utils import get_user_form, parse_enabled_sites
from .forms import UserForm
from ...models import User, AccountRequest, db
from ...utils import report_form_errors, dashboard_admin_required


@lm.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


@user_bp.before_app_request
def before_request():
    if current_user.is_authenticated and not current_user.is_active:
        logout_user()
        flash('Your account is disabled. Please contact an administrator.')
        return


@user_bp.route('/login')
def login():
    next_url = request.args.get('next')
    if next_url:
        flask_session['next_url'] = next_url
    return render_template('login.html')


@user_bp.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('users.login'))


@user_bp.route('/refresh_login')
def refresh_login():
    flask_session['_fresh'] = False
    next_url = request.args.get('next')
    if next_url:
        flask_session['next_url'] = next_url
    return redirect(url_for('users.login'))


@user_bp.route('/', methods=['GET', 'POST'])
@user_bp.route('/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user(user_id=None):

    if user_id and (user_id != current_user.id
                    and not current_user.dashboard_admin):
        flash("You are not authorized to view other user settings")
        return redirect(url_for('users.user'))

    if user_id:
        user = db.session.get(User, user_id)
    else:
        user = current_user

    form = get_user_form(user, current_user)

    if form.validate_on_submit():
        submitted_id = form.id.data

        if (submitted_id != current_user.id
                and not current_user.dashboard_admin):
            # This catches anyone who tries to modify the user_id submitted
            # with the form to change other user's settings
            flash("You are not authorized to update other users' settings.")
            return redirect(url_for('users.user'))

        updated_user = db.session.get(User, submitted_id)

        if form.update_access.data:
            # Give user access to a new study or site
            enabled = parse_enabled_sites(form.add_access.data)
            updated_user.add_studies(enabled)
        elif form.revoke_all_access.data:
            # Revoke access to all enabled studies
            revoked = {s: [] for s in user.studies}
            updated_user.remove_studies(revoked)
        else:
            # Update user info
            form.populate_obj(updated_user)

        # Check if a single study (or site in a study) has been disabled
        removed_studies = {
            sf.study_id.data: [sf.site_id.data] if sf.site_id.data else []
            for sf in form.studies if sf.revoke_access.data
        }
        if removed_studies:
            updated_user.remove_studies(removed_studies)

        updated_user.save()

        flash("User profile updated.")
        return redirect(url_for('users.user', user_id=submitted_id))

    report_form_errors(form)

    return render_template('profile.html', user=user, form=form)


@user_bp.route('/manage')
@user_bp.route('/manage/<int:user_id>/account/<approve>')
@login_required
@dashboard_admin_required
def manage_users(user_id=None, approve=False):
    users = User.query.all()
    # study_requests = []

    if not user_id:
        return render_template('manage_users.html',
                               users=users,
                               account_requests=AccountRequest.query.all())

    if approve == "False":
        # URL gets parsed into unicode
        approve = False

    user_request = db.session.get(AccountRequest, user_id)
    if not approve:
        try:
            user_request.reject()
        except Exception:
            flash("Failed while rejecting account request for user {}".format(
                user_id))
        else:
            flash('Account rejected.')
        return render_template('manage_users.html',
                               users=users,
                               account_requests=AccountRequest.query.all())

    try:
        user_request.approve()
    except Exception:
        flash('Failed while trying to activate account for user {}'.format(
            user_id))
    else:
        flash('Account access for {} enabled'.format(user_id))

    return render_template('manage_users.html',
                           users=users,
                           account_requests=AccountRequest.query.all())


@user_bp.route('/new_account', methods=['GET', 'POST'])
def new_account():
    request_form = UserForm()
    if request_form.validate_on_submit():
        first = request_form.first_name.data
        last = request_form.last_name.data
        new_user = User(first,
                        last,
                        username=request_form.account.data,
                        provider=request_form.provider.data)
        new_user.request_account(request_form)
        flash("Request submitted. Please allow up to 2 days for a response "
              "before contacting an admin.")
        return redirect(url_for('users.login'))
    if request_form.is_submitted:
        report_form_errors(request_form)
    return render_template('account_request.html', form=request_form)
