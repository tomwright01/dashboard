"""Database models + relations
"""
import os
import datetime
import logging
from abc import abstractmethod
from random import randint

from flask import current_app
from flask_login import UserMixin, AnonymousUserMixin
from sqlalchemy import and_, or_, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import deferred, backref
from sqlalchemy.schema import UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.orm.exc import FlushError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.associationproxy import association_proxy
from psycopg2.tz import FixedOffsetTimezone
from sqlalchemy.orm.collections import attribute_mapped_collection

from datman import scanid, header_checks
from dashboard import db, TZ_OFFSET
from dashboard.exceptions import InvalidDataException
from dashboard.models import utils
from .emails import (account_request_email, account_activation_email,
                     account_rejection_email, qc_notification_email)

logger = logging.getLogger(__name__)


class TableMixin:
    """Adds simple methods commonly needed for tables.
    """

    def save(self):
        db.session.add(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to commit to database. Reason "
                                       "- {}".format(e))

    def delete(self):
        db.session.delete(self)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to delete from database. "
                                       "Reason - {}".format(e))


class PermissionMixin:
    """Adds methods needed for user authentication.
    """

    @abstractmethod
    def get_studies(self):
        pass

    @abstractmethod
    def get_sites(self):
        pass

    @abstractmethod
    def get_disabled_sites(self):
        pass

    @abstractmethod
    def _get_permissions(self, study, site=None, perm=None):
        pass

    def has_study_access(self, study, site=None):
        return self._get_permissions(study, site)

    def is_study_admin(self, study, site=None):
        return self._get_permissions(study, site, perm='is_admin')

    def is_primary_contact(self, study, site=None):
        return self._get_permissions(study, site, perm='primary_contact')

    def is_kimel_contact(self, study, site=None):
        return self._get_permissions(study, site, perm='kimel_contact')

    def is_study_RA(self, study, site=None):
        return self._get_permissions(study, site, perm='study_RA')

    def does_qc(self, study, site=None):
        return self._get_permissions(study, site, perm='does_qc')


###############################################################################
# Association tables (i.e. basic many to many relationships)

study_timepoints_table = db.Table(
    'study_timepoints',
    db.Column('study',
              db.String(32),
              db.ForeignKey('studies.id'),
              nullable=False),
    db.Column('timepoint',
              db.String(64),
              db.ForeignKey('timepoints.name'),
              nullable=False), UniqueConstraint('study', 'timepoint'))

###############################################################################
# Plain entities


class User(PermissionMixin, UserMixin, TableMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column('id', db.Integer, primary_key=True)
    first_name = db.Column('first_name', db.String(64), nullable=False)
    last_name = db.Column('last_name', db.String(64), nullable=False)
    email = db.Column('email', db.String(256))
    position = db.Column('position', db.String(64))
    institution = db.Column('institution', db.String(128))
    phone = db.Column('phone', db.String(20))
    ext = db.Column('ext', db.String(10))
    alt_phone = db.Column('alt_phone', db.String(20))
    alt_ext = db.Column('alt_ext', db.String(10))
    _username = db.Column('username', db.String(70))
    picture = db.Column('picture', db.String(2048))
    dashboard_admin = db.Column('dashboard_admin', db.Boolean, default=False)
    is_active = db.Column('account_active', db.Boolean, default=False)

    studies = db.relationship(
        'StudyUser',
        back_populates='user',
        order_by='StudyUser.study_id',
        collection_class=lambda: utils.DictListCollection('study_id'),
        cascade="all, delete-orphan")
    incidental_findings = db.relationship('IncidentalFinding')
    scan_comments = db.relationship('ScanChecklist')
    timepoint_comments = db.relationship('TimepointComment')
    analysis_comments = db.relationship('AnalysisComment')
    sessions_reviewed = db.relationship('Session')
    pending_approval = db.relationship('AccountRequest',
                                       uselist=False,
                                       cascade="all, delete")

    __table_args__ = (UniqueConstraint(_username),)

    def __init__(self,
                 first,
                 last,
                 username=None,
                 provider='github',
                 email=None,
                 position=None,
                 institution=None,
                 phone=None,
                 ext=None,
                 alt_phone=None,
                 alt_ext=None,
                 picture=None,
                 dashboard_admin=False,
                 account_active=False):
        self.first_name = first
        self.last_name = last
        self.email = email
        self.position = position
        self.institution = institution
        self.phone = phone
        self.ext = ext
        self.alt_phone = alt_phone
        self.alt_ext = alt_ext
        if username:
            self.update_username(username, provider)
        self.picture = picture
        self.dashboard_admin = dashboard_admin
        self.account_active = account_active

    def update_username(self, new_name, provider='github'):
        # Make sure the username is globally unique by adding a prefix based on
        # the oauth provider
        if provider == 'github':
            self._username = "gh_" + new_name
        else:
            # gitlab is the only alt provider for now
            self._username = "gl_" + new_name

    @property
    def username(self):
        try:
            uname = "_".join(self._username.split("_")[1:])
        except AttributeError:
            uname = ""
        return uname

    @property
    def account_provider(self):
        if not self._username:
            return None
        if self._username.startswith('gl_'):
            return 'gitlab'
        return 'github'

    def update_avatar(self, url=None):
        if url is None or url == self.picture:
            return
        self.picture = url
        self.save()

    def request_account(self, request_form):
        request_form.populate_obj(self)
        # This is needed because the form sets it to an empty string, which
        # causes postgres to throw an error (it expects an int)
        self.id = None
        try:
            self.save()
            request = AccountRequest(self.id)
            request.save()
        except IntegrityError:
            # Account exists or request is already pending
            db.session.rollback()
        else:
            utils.schedule_email(account_request_email,
                                 [str(self)])

    def num_requests(self):
        """
        Returns a count of all pending user requests that need to be reviewed
        """
        if not self.dashboard_admin:
            return 0
        return AccountRequest.query.count()

    def add_studies(self, study_ids):
        """Enable study access for this user.

        This will add a StudyUser record with the default permissions for
        each given study. Restrict access to specific sites by mapping the
        study ID to a list of allowed site names. An empty list means 'grant
        the user access to all sites'.

        For example:

            study_ids = {'OPT': ['UT1', 'UT2'],
                         'PRELAPSE': []}

        This would grant the user access to two sites (UT1, UT2) in OPT and
        all sites in PRELAPSE.

        Args:
            study_ids (:obj:`dict`): A dictionary of study IDs to grant user
                access to. Each study ID key should map to a list of sites
                to enable. Use the empty list to indicate global study access.

        Raises:
            InvalidDataException: If the format of arg study_ids is incorrect
                or one or more records cannot be added.

        """
        if not isinstance(study_ids, dict):
            raise InvalidDataException("User.add_studies expects a dictionary "
                                       "of permission settings. Received {}"
                                       "".format(type(study_ids)))

        for study in study_ids:
            if not study_ids[study]:
                db.session.add(StudyUser(study, self.id))
            else:
                for site in study_ids[study]:
                    db.session.add(StudyUser(study, self.id, site_id=site))
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            raise InvalidDataException("Failed to update user {}'s study "
                                       "access. Reason - {}"
                                       "".format(self.id, e._message()))

    def remove_studies(self, study_ids):
        """Disable study access for this user.

        This removes any StudyUser records that match the given study IDs.
        Access to specific sites within a study can be disabled by mapping
        the study ID to a list of site names. An empty list means 'disable
        user access to this study completely'.

        For example:

            study_ids = {'OPT': ['UT1'],
                         'PRELAPSE': []}

        This would remove user access to site 'UT1' for OPT and totally
        disable user access to PRELAPSE

        Args:
            study_ids (:obj:`dict`): A dictionary of study IDs to disable
                access to. Each ID should map to a list of sites to disable.
                The empty list indicates complete access restriction

        Raises:
            InvalidDataException: If the format of arg study_ids is incorrect
                or one or more records cannot be removed.
        """
        if not isinstance(study_ids, dict):
            raise InvalidDataException("User.remove_studies expects a "
                                       "dictionary of permission settings. "
                                       "Received {}".format(type(study_ids)))

        for study in study_ids:
            if study not in self.studies:
                continue
            if not study_ids[study]:
                [db.session.delete(su) for su in self.studies[study]]
            else:
                for site in study_ids[study]:
                    found = [
                        item for item in self.studies[study]
                        if item.site_id == site
                    ]
                    if not found:
                        continue
                    db.session.delete(found[0])

        try:
            db.session.commit()
        except Exception as e:
            raise InvalidDataException("Failed to restrict study access for "
                                       "user {}. Reason - {}".format(
                                           self.id, e))

    def get_studies(self):
        """Get a list of studies that user has even partial access to

        Returns:
            list: A list of Study objects, one for each study where the user
            has at least partial (site based) access.
        """
        if self.dashboard_admin:
            studies = Study.query.order_by(Study.id).all()
        else:
            studies = sorted(
                [su[0].study for su in self.studies.values()],
                key=lambda x: x.id
            )
        return studies

    def get_sites(self):
        """Get a list of sites the user has even partial access to.

        Caution: If using this to determine data access you must still restrict
        by study.

        Returns:
            list: A list of string site names.
        """
        if self.dashboard_admin:
            sites = [item[0]
                     for item in Site.query.with_entities(Site.name).all()]
        else:
            sites = set()
            for study in self.studies:
                for study_site in self.studies[study]:
                    if not study_site.site_id:
                        # All sites are enabled
                        sites = sites.union(study_site.study.sites)
                    else:
                        sites.add(study_site.site_id)
        return list(sorted(sites))

    def get_disabled_sites(self):
        """Get a dict of study IDs mapped to sites this user cant access

        Returns:
            dict: A dictionary mapping each study ID to a list of its sites
            that this user does not have access to. Studies where the user
            has full access will be omitted entirely.
        """
        disabled = StudySite.query \
            .with_entities(StudySite.study_id, StudySite.site_id) \
            .filter(~exists().where(
                and_(StudyUser.user_id == self.id,
                     StudyUser.study_id == StudySite.study_id,
                     or_(StudyUser.site_id == StudySite.site_id,
                         StudyUser.site_id == None)))) \
            .order_by(StudySite.study_id.asc())

        found = {}
        for study, site in disabled:
            found.setdefault(study, []).append(site)
        return found

    def _get_permissions(self, study, site=None, perm=None):
        """Check if a user has general access rights or a specific permission

        Checks StudyUser records for this user.
            - If only study is set, it will check if the user has any access
            to the study at all
            - If study and perm are set, it will check if the user
            has the named permission for that entire study

        Use the 'site' flag to restrict checks to specific sites instead of
        the study as a whole.

        Example:
            study = 'SPINS', perm = 'study_RA' will check if the user is
            declared as a 'study_RA' for the every site in 'SPINS'.
            Setting site='CMH' for the same check will restrict it to
            checking whether the user is an RA for 'CMH'

        Args:
            study (str): The ID for a managed study
            site (str, optional): The ID of a site within the study
            perm (str, optional): The name of a specific user permission to
            check. e.g. 'is_admin' or 'does_qc'

        Returns:
            bool: False if the user should be denied, True otherwise
        """
        if self.dashboard_admin:
            return True

        if isinstance(study, Study):
            study = study.id
        if site and isinstance(site, Site):
            site = site.name

        try:
            access_rights = self.studies[study]
        except KeyError:
            return False

        if site:
            access_rights = [su for su in access_rights
                             if su.site_id is None or su.site_id == site]
            if not access_rights:
                return False

        if perm:
            return getattr(access_rights[0], perm)

        return True

    def __repr__(self):
        return "<User {}: {} {}>".format(self.id, self.first_name,
                                         self.last_name)

    def __str__(self):
        return "{} {}".format(self.first_name, self.last_name)


class AnonymousUser(PermissionMixin, AnonymousUserMixin):
    # This is only used by devel instances of the dashboard
    # It's safe to give the anonymous user full access to studies
    # because when LOGIN_DISABLED=False, this user cant access views
    # However, it's NOT safe to give the anonymous user 'dashboard_admin' or
    # 'account_active' status, be careful :)

    id = -1
    dashboard_admin = False
    account_active = False
    first_name = "Guest"

    def get_studies(self):
        return Study.query.order_by(Study.id).all()

    def get_sites(self):
        return sorted([site.name for site in Site.query.all()])

    def get_disabled_sites(self):
        return {}

    def _get_permissions(self, study, site=None, perm=None):
        return True

    def __repr__(self):
        return "<AnonymousUser>"


class AccountRequest(TableMixin, db.Model):
    __tablename__ = 'account_requests'

    user_id = db.Column('user_id',
                        db.Integer,
                        db.ForeignKey("users.id", ondelete='CASCADE'),
                        primary_key=True)
    user = db.relationship('User', uselist=False)

    def __init__(self, user_id):
        self.user_id = user_id

    def approve(self):
        try:
            self.user.is_active = True
            db.session.delete(self)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Account activation failed for user {}. Reason: "
                         "{}".format(self.user_id, e))
            raise e
        else:
            user = self.user
            utils.schedule_email(
                account_activation_email,
                [user.username, user.email, len(user.studies)])

    def reject(self):
        try:
            db.session.delete(self.user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Account request rejection failed for user {}. "
                         "Reason: {}".format(self.user_id, e))
            raise e
        else:
            user = self.user
            utils.schedule_email(account_rejection_email,
                                 [user.id, user.email])

    def __repr__(self):
        return "<User {} Requires Admin Review>".format(self.user_id)

    def __str__(self):
        if self.user:
            result = "{} {} requests access under username {}".format(
                self.user.first_name, self.user.last_name, self.user.username)
        else:
            result = "User with ID {} requests dashboard access".format(
                self.user_id)
        return result


class Study(TableMixin, db.Model):
    __tablename__ = 'studies'

    id = db.Column('id', db.String(32), primary_key=True)
    name = db.Column('name', db.String(1024))
    description = db.Column('description', db.Text)
    read_me = deferred(db.Column('read_me', db.Text))
    is_open = db.Column('is_open', db.Boolean, default=True, nullable=False)
    email_qc = db.Column('email_on_trigger', db.Boolean)

    users = db.relationship(
        'StudyUser',
        primaryjoin='and_(Study.id==foreign(StudyUser.study_id), '
                    'StudySite.study_id==StudyUser.study_id)',
        cascade='all, delete',
    )
    sites = db.relationship(
        'StudySite',
        back_populates='study',
        collection_class=attribute_mapped_collection('site_id'),
        cascade="all, delete",
    )
    scantypes = db.relationship(
        'ExpectedScan',
        collection_class=lambda: utils.DictListCollection('site_id'),
        cascade="all, delete",
    )
    timepoints = db.relationship(
        'Timepoint',
        secondary=study_timepoints_table,
        back_populates='studies',
        lazy='dynamic',
        cascade="all, delete",
    )
    standards = db.relationship(
        'GoldStandard',
        secondary='expected_scans',
        collection_class=lambda: utils.DictListCollection('site'),
        viewonly=True,
    )
    _pipelines = db.relationship('StudyPipeline', cascade='all, delete')

    def __init__(self,
                 study_id,
                 full_name=None,
                 description=None,
                 read_me=None,
                 is_open=None):
        self.id = study_id
        self.full_name = full_name
        self.description = description
        self.read_me = read_me
        self.is_open = is_open

    def add_timepoint(self, timepoint):
        if isinstance(timepoint, scanid.Identifier):
            timepoint = Timepoint(
                timepoint.get_full_subjectid_with_timepoint(),
                timepoint.site,
                is_phantom=scanid.is_phantom(timepoint))

        if not isinstance(timepoint, Timepoint):
            raise InvalidDataException(
                "Invalid input to 'add_timepoint()': "
                "instance of dashboard.models.Timepoint or "
                "datman.scanid.Identifier expected")

        if timepoint.site_id not in self.sites.keys():
            raise InvalidDataException("Timepoint's site {} is not configured "
                                       "for study {}".format(
                                           timepoint.site_id, self.id))
        self.timepoints.append(timepoint)
        try:
            db.session.add(self)
            db.session.commit()
        except FlushError:
            db.session.rollback()
            raise InvalidDataException("Can't add timepoint {}. Already "
                                       "exists.".format(timepoint))
        except Exception as e:
            db.session.rollback()
            e.message = "Failed to add timepoint {}. Reason: {}".format(
                timepoint, e)
            raise

        if self.email_qc:
            not_qcd = [t.name for t in self.timepoints.all() if not
                       t.is_qcd()]
            _ = [utils.schedule_email(qc_notification_email,
                                      [str(u), u.email, self.id,
                                       timepoint.name, not_qcd])
                 for u in self.get_QCers()]

        return timepoint

    def add_gold_standard(self, gs_file):
        try:
            new_gs = GoldStandard(self.id, gs_file)
        except OSError:
            raise InvalidDataException("Can't add gold standard, file not "
                                       "readable: {}".format(gs_file))
        try:
            db.session.add(new_gs)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            str_err = str(e)
            if 'not present in table "expected_scans"' in str_err:
                raise InvalidDataException(
                    "Attempted to add gold standard with invalid "
                    "Study/Site/Tag combination."
                )
            else:
                raise InvalidDataException(
                    "Failed to add gold standard {}. Reason - "
                    "{}".format(gs_file, e)
                )
        return new_gs

    def delete_scantype(self, site_id, scantype):
        if site_id not in self.sites:
            raise InvalidDataException(
                "Invalid site {} for {}".format(site_id, self.id)
            )

        found = [entry for entry in self.scantypes[site_id]
                 if entry.scantype_id == scantype]
        if not found:
            return
        found[0].delete()

    def delete_site(self, site):
        if site not in self.sites:
            return
        study_site = self.sites[site]
        site = study_site.site
        study_site.delete()
        if not site.studies:
            site.delete()

    def update_site(self, site_id, redcap=None, notes=None, code=None,
                    xnat_archive=None, xnat_convention="KCNI",
                    xnat_credentials=None, xnat_url=None, create=False):
        """Update a site configured for this study (or configure a new one).

        Args:
            site_id (str or Site): The ID of a site associated with this study
                or its record from the database.
            redcap (bool, optional): True if redcap scan completed records are
                used by this site. Updates only if value provided.
                Defaults to None.
            notes (bool, optional): True if tech notes are provided by this
                site. Updates only if value provided. Defaults to None.
            code (str, optional): The study code used for IDs for this study
                and site combination. Updates only if value provided.
                Defaults to None.
            xnat_archive (str, optional): The name of the archive on XNAT
                where data for this site is stored. Updates only if value
                provided. Defaults to None.
            xnat_convention (str, optional): The naming convention used
                on the XNAT server for this site. Defaults to 'KCNI'.
            xnat_credentials (str, optional): The full path to the credentials
                file to read when accessing this site's XNAT archive.
                Defaults to None.
            xnat_url (str, optional): The URL to use when accessing this
                site's XNAT archive. Defaults to None.
            create (bool, optional): Whether to create the site and add it
                to this study if it isnt already associated. Defaults to False.

        Raises:
            InvalidDataException: If the site doesnt exist or isn't associated
                with this study (and create wasnt given) or if the update
                fails.
        """
        if isinstance(site_id, Site):
            site_id = Site.id
        elif not db.session.get(Site, site_id):
            if not create:
                raise InvalidDataException("Site {} does not exist.".format(
                    site_id))
            site = Site(site_id)
            db.session.add(site)

        if site_id not in self.sites:
            if not create:
                raise InvalidDataException("Invalid site {} for study "
                                           "{}".format(site_id, self.id))
            study_site = StudySite(self.id, site_id)
        else:
            study_site = self.sites[site_id]

        if redcap is not None:
            study_site.uses_redcap = redcap

        if notes is not None:
            study_site.uses_notes = notes

        if code is not None:
            study_site.code = code

        if xnat_archive is not None:
            study_site.xnat_archive = xnat_archive

        study_site.xnat_convention = xnat_convention

        if xnat_credentials is not None:
            study_site.xnat_credentials = xnat_credentials

        if xnat_url is not None:
            study_site.xnat_url = xnat_url

        db.session.add(study_site)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException(
                "Failed to update site {} for study {}. Reason - {}".format(
                    site_id, self.id, e
                )
            )

    def update_scantype(self, site_id, scantype, num=None, pha_num=None,
                        create=False):
        """Update the number of scans expected for each site / tag combination.

        Args:
            site_id (str or Site): The site to configure.
            scantype (str or Scantype): The scan type to configure.
            num (int, optional): The number of scans expected with this tag for
                human subjects at this site. Only updates if value given.
                Defaults to None.
            pha_only (int, optional): The number of scans with this tag
                expected for phantoms at this site. Only updates if value
                given. Defaults to None.
            create (bool, optional): Whether to add a new record for the
                study/site/tag combination if one doesnt exist.

        Raises:
            InvalidDataException: If a site is given that isn't configured for
                this study, if the scan type does not exist, or if an error
                occurs during database update.
        """
        if isinstance(site_id, Site):
            site_id = site_id.id

        if site_id not in self.sites:
            raise InvalidDataException("Invalid site {} for {}".format(
                site_id, self.id))

        if not isinstance(scantype, Scantype):
            found = db.session.get(Scantype, scantype)
            if not found:
                raise InvalidDataException("Undefined scan type "
                                           "{}.".format(scantype))
            scantype = found

        expected = db.session.get(ExpectedScan,
                                  (self.id, site_id, scantype.tag))
        if expected:
            if num:
                expected.count = num
            if pha_num:
                expected.pha_count = pha_num
        elif create:
            expected = ExpectedScan(self.id, site_id, scantype.tag, num,
                                    pha_num)
        else:
            raise InvalidDataException(
                "Tag {} not accepted for study {} and site {} combination."
                "".format(scantype.tag, self.id, site_id)
            )

        db.session.add(expected)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to update expected scans for "
                                       "{}. Reason - {}".format(self.id, e))

    def num_timepoints(self, type=''):
        if type.lower() == 'human':
            timepoints = [
                timepoint for timepoint in self.timepoints
                if not timepoint.is_phantom
            ]
        elif type.lower() == 'phantom':
            timepoints = [
                timepoint for timepoint in self.timepoints
                if timepoint.is_phantom
            ]
        else:
            timepoints = self.timepoints
        return len(timepoints)

    def outstanding_issues(self):
        # Get a tuple of Session.name, Session.num like from
        # the other two queries
        new_sessions_q = select(Session.name, Session.num).where(
            Session.name.in_(self.get_new_sessions()))
        new_sessions = db.session.execute(new_sessions_q).all()

        missing_redcap = self.get_missing_redcap()
        missing_scans = self.get_missing_scans()

        new_label = '<td class="col-xs-2"><span class="fa-layers fa-fw" ' + \
                    'style="font-size: 28px;"><i class="fas ' + \
                    'fa-certificate" style="color: tomato"></i>' + \
                    '<span class="fa-layers-text fa-inverse" ' + \
                    'data-fa-transform="shrink-11.5 rotate--30" ' + \
                    'style="font-weight:900">NEW</span></span></td>'
        scans_label = '<td class="col-xs-2"><span class="label ' + \
                      'qc-warnings label-warning" title="Participant ' + \
                      'exists in REDCap but does not have scans">Missing ' + \
                      'Scans</span></td>'
        redcap_label = '<td class="col-xs-2"><span class="label ' + \
                       'qc-warnings label-info" title="Participant ' + \
                       'does not have a REDCap survey even though this ' + \
                       'scan site collects them">Missing REDCap</span></td>'

        issues = {}
        # Using default_row[:] in setdefault() to make sure each row has its
        # own copy of the default row
        default_row = ['<td></td>'] * 4
        for session in new_sessions:
            issues.setdefault(session[0], default_row[:])[0] = new_label
        for session in missing_scans:
            issues.setdefault(session[0], default_row[:])[2] = scans_label
        for session in missing_redcap:
            issues.setdefault(session[0], default_row[:])[3] = redcap_label

        return issues

    def get_new_sessions(self):
        # Doing this 'manually' to prevent SQLAlchemy from sending one query
        # per timepoint per study
        new = db.session.query(Session.name) \
                .join(Timepoint) \
                .join(study_timepoints_table,
                      and_((study_timepoints_table.c.timepoint ==
                            Timepoint.name),
                           study_timepoints_table.c.study == self.id)) \
                .filter(Session.signed_off == False) \
                .filter(Timepoint.is_phantom == False) \
                .group_by(Session.name)

        return new

    def get_sessions_using_redcap(self):
        """
        Returns a query that will find all sessions in the current study that
        expect a redcap survey (whether or not we've already received one for
        them)

        Doing this manually rather than letting SQLAlchemy handle it behind
        the scenes because it was firing off one query per session every time a
        study page loaded. So it's way uglier, but way faster. Sorry :(
        """
        uses_redcap = db.session.query(Session, SessionRedcap) \
                        .outerjoin(SessionRedcap) \
                        .join(Timepoint) \
                        .join(study_timepoints_table,
                              and_((study_timepoints_table.c.timepoint ==
                                    Timepoint.name),
                                   study_timepoints_table.c.study == self.id))\
                        .join(StudySite,
                              and_(StudySite.site_id == Timepoint.site_id,
                                   (StudySite.study_id ==
                                    study_timepoints_table.c.study))) \
                        .filter(Timepoint.is_phantom == False) \
                        .filter(StudySite.uses_redcap == True)

        return uses_redcap

    def get_missing_redcap(self):
        """
        Returns a list of all non-phantoms for the current study
        that are expecting a redcap survey but dont yet have one.
        """
        uses_redcap = self.get_sessions_using_redcap()
        sessions = uses_redcap.filter(SessionRedcap.name == None) \
            .with_entities(Session.name, Session.num)
        return sessions.all()

    def get_missing_scans(self):
        """
        Returns a list of session names + repeat numbers for sessions in this
        study that have a scan completed survey but no scan data yet. Excludes
        session IDs that have explicitly been marked as never expecting data
        """
        uses_redcap = self.get_sessions_using_redcap()
        sessions = uses_redcap.filter(
            SessionRedcap.record_id != None).filter(~exists().where(
                and_(Scan.timepoint == Session.name, Scan.repeat ==
                     Session.num))).filter(~exists().where(
                         and_(Session.name == EmptySession.name, Session.num ==
                              EmptySession.num))).with_entities(
                                  Session.name, Session.num)
        return sessions.all()

    def get_blacklisted_scans(self):
        query = self._get_checklist()
        blacklisted_scans = query.filter(
            and_(ScanChecklist.approved == False,
                 ScanChecklist.comment != None))
        return blacklisted_scans.all()

    def get_flagged_scans(self):
        query = self._get_checklist()
        flagged_scans = query.filter(
            and_(ScanChecklist.approved == True,
                 ScanChecklist.comment != None))
        return flagged_scans.all()

    def get_qced_scans(self):
        query = self._get_checklist()
        reviewed_scans = query.filter(
            and_(ScanChecklist.approved == True,
                 ScanChecklist.comment == None))
        return reviewed_scans.all()

    def get_tag_counts(self, site, pha=False):
        """Return the number of scans expected for each tag.

        Args:
            site (str): The name of a site for this study.
            pha (bool, optional): Whether to look up the number expected
                for phantoms.
        """
        if not pha:
            return {
                item.scantype_id: item.count for item in self.scantypes[site]
            }
        return {
            item.scantype_id: item.pha_count for item in self.scantypes[site]
        }

    def _get_checklist(self):
        query = db.session.query(ScanChecklist) \
                          .join(Scan) \
                          .join(study_timepoints_table,
                                and_((study_timepoints_table.c.timepoint ==
                                      Scan.timepoint),
                                     (study_timepoints_table.c.study ==
                                      self.id)))
        return query

    def get_primary_contacts(self):
        contacts = [
            study_user.user for study_user in self.users
            if study_user.primary_contact
        ]
        return contacts

    def get_staff_contacts(self):
        return [su.user for su in self.users if su.kimel_contact]

    def get_RAs(self, site=None, unique=False):
        """
        Get a list of all RAs for the study, or all RAs for a given site.

        The 'unique' flag can be used to ensure RAs are only in the list once
        if they happen to be an RA for multiple sites. Pretty much only useful
        for printing the list.
        """
        if site:
            # Get all users who are an RA for this specific site or
            # an RA for the whole study
            RAs = [
                su.user for su in self.users
                if su.study_RA and (not su.site_id or su.site_id == site)
            ]
        else:
            # Get all RAs for the study
            RAs = [su.user for su in self.users if su.study_RA]
        if unique:
            found = {}
            for user in RAs:
                found[str(user)] = user
            RAs = [found[key] for key in found]
        return RAs

    def get_QCers(self):
        return [su.user for su in self.users if su.does_qc]

    def choose_staff_contact(self):
        contacts = self.get_staff_contacts()
        if len(contacts) >= 1:
            user = self.select_next(contacts)
        else:
            user = None
        return user

    def select_next(self, user_list):
        """
        Selects the next user from a study. This can be used to choose
        the next QC-er to assign, or the next staff member to assign to an
        issue, etc.

        Current strategy is to pick a random person. This may be changed in
        the future.
        """
        next_idx = randint(0, len(user_list) - 1)
        return user_list[next_idx]

    def delete(self):
        for study_site in self.sites.values():
            if len(study_site.site.studies) == 1:
                # Clean up sites not used by any other study
                study_site.site.delete()
        for site in self.scantypes:
            for expected_scan in self.scantypes[site]:
                if len(expected_scan.scantype.studies) == 1:
                    # Clean up tags not used by any other study
                    expected_scan.scantype.delete()
        super().delete()

    def get_pipelines(self, scope=None):
        if scope:
            return [item for item in self._pipelines if item.scope == scope]
        return self._pipelines

    def add_pipeline(self, pipeline_key, view, name, scope):
        record = db.session.get(StudyPipeline, (self.id, pipeline_key))
        if not record:
            record = StudyPipeline(study_id=self.id, pipeline_id=pipeline_key)
        record.view = view
        record.name = name
        record.scope = scope
        record.save()
        return record

    def __repr__(self):
        return "<Study {}>".format(self.id)


class Site(TableMixin, db.Model):
    __tablename__ = 'sites'

    name = db.Column('name', db.String(32), primary_key=True)
    description = db.Column('description', db.Text)

    studies = db.relationship(
        'StudySite',
        back_populates='site',
        collection_class=attribute_mapped_collection('study.id'),
        cascade="all, delete"
    )
    timepoints = db.relationship('Timepoint', cascade="all, delete")

    def __init__(self, site_name, description=None):
        self.name = site_name
        self.description = description

    def __repr__(self):
        return "<Site {}>".format(self.name)


class Timepoint(TableMixin, db.Model):
    __tablename__ = 'timepoints'

    name = db.Column('name', db.String(64), primary_key=True)
    bids_name = db.Column('bids_name', db.Text)
    bids_session = db.Column('bids_sess', db.String(48))
    kcni_name = db.Column('kcni_name', db.String(48))
    site_id = db.Column('site',
                        db.String(32),
                        db.ForeignKey('sites.name'),
                        nullable=False)
    is_phantom = db.Column('is_phantom',
                           db.Boolean,
                           nullable=False,
                           default=False)

    site = db.relationship('Site', uselist=False, back_populates='timepoints')
    studies = db.relationship(
        'Study',
        secondary=study_timepoints_table,
        back_populates='timepoints',
        collection_class=attribute_mapped_collection('id'))
    sessions = db.relationship(
        'Session',
        lazy='joined',
        collection_class=attribute_mapped_collection('num'),
        cascade='all, delete')
    comments = db.relationship('TimepointComment',
                               cascade='all, delete',
                               order_by='TimepointComment._timestamp')
    incidental_findings = db.relationship('IncidentalFinding',
                                          cascade='all, delete')

    def __init__(self, name, site, is_phantom=False):
        self.name = name
        self.site_id = site
        self.is_phantom = is_phantom

    def add_bids(self, name, session):
        self.bids_name = name
        self.bids_session = session
        self.save()

    def get_study(self, study_id=None):
        """
        Most timepoints only ever have one study and this will just return
        the first one found. If 'id' is given it will either return the study
        object or raise an exception if this timepoint doesnt belong to that
        study
        """
        if study_id:
            try:
                return self.studies[study_id]
            except KeyError:
                raise InvalidDataException("Timepoint {} does not belong to "
                                           "study {}".format(self, study_id))
        try:
            study = list(self.studies.values())[0]
        except IndexError:
            raise InvalidDataException("Timepoint {} does not have any "
                                       "studies configured.".format(self))
        return study

    def add_session(self, num, date=None):
        try:
            self.sessions[num]
        except KeyError:
            # Session doesnt exist yet so it's safe to proceed
            pass
        else:
            raise InvalidDataException("Session {} of timepoint {} already "
                                       "exists.".format(num, self.name))

        if self.is_phantom and num > 1:
            raise InvalidDataException("Cannot add repeat session {} to "
                                       "phantom {}".format(num, self.name))

        session = Session(self.name, num, date=date)
        self.sessions[num] = session
        try:
            db.session.add(self)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            e.message = "Failed to add session {} to timepoint {}. Reason: " \
                        "{}".format(num, self.name, e)
            raise
        return session

    def get_blacklist_entries(self):
        """
        Returns any ScanChecklist entries for blacklisted scans for
        every session belonging to this timepoint.
        """
        entries = []
        for session in self.sessions.values():
            entries.extend(session.get_blacklist_entries())
        return entries

    def belongs_to(self, study):
        """
        Returns true if the data in this Timepoint is considered part of the
        given study
        """
        if isinstance(study, Study):
            study = study.id
        try:
            self.studies[study]
        except KeyError:
            return False
        return True

    def accessible_study(self, user):
        """
        Returns a study that the timepoint belongs to and the user has access
        to if one exists.
        """
        for study_name in self.studies:
            if user.has_study_access(study_name, self.site_id):
                return self.studies[study_name]
        return None

    def is_qcd(self):
        if self.is_phantom:
            return True
        return all(sess.is_qcd() for sess in self.sessions.values())

    @property
    def reviewer(self):
        """
        Returns the name of the first session's qc reviewer as this timepoint's
        reviewer
        """
        if not self.is_qcd():
            return ''
        return list(self.sessions.values())[0].reviewer

    def expects_redcap(self, study=None):
        if self.is_phantom:
            return False
        if not study:
            study = list(self.studies.keys())[0]
        return self.site.studies[study].uses_redcap

    def needs_redcap_survey(self, study_id):
        uses_redcap = self.expects_redcap(study_id)
        return uses_redcap and any(not sess.redcap_record
                                   for sess in self.sessions.values())

    def expects_notes(self, study=None):
        if self.is_phantom:
            return False
        study = self.get_study(study)
        study_site = study.sites[self.site.name]
        return study_site.uses_notes

    def missing_scans(self):
        if self.is_phantom:
            return False
        return any(sess.missing_scans() for sess in self.sessions.values())

    def dismiss_redcap_error(self, session_num):
        existing = db.session.get(SessionRedcap, (self.name, session_num))
        if existing:
            return
        session_redcap = SessionRedcap(self.name, session_num)
        db.session.add(session_redcap)
        db.session.commit()

    def ignore_missing_scans(self, session_num, user_id, comment):
        empty_session = EmptySession(self.name, session_num, user_id, comment)
        db.session.add(empty_session)
        db.session.commit()

    def delete(self):
        """
        This will cascade and also delete any records that reference
        the current timepoint, so be careful :)
        """
        for num in self.sessions:
            self.sessions[num].delete()
        db.session.delete(self)
        db.session.commit()

    def report_incidental_finding(self, user_id, comment):
        new_finding = IncidentalFinding(user_id, self.name, comment)
        db.session.add(new_finding)
        db.session.commit()

    def update_comment(self, user_id, comment_id, new_text):
        comment = self.get_comment(comment_id)
        if user_id != comment.user_id:
            raise Exception('User does not have permission to modify comment')
        comment.update(new_text)

    def add_comment(self, user_id, text):
        new_comment = TimepointComment(self.name, user_id, text)
        db.session.add(new_comment)
        db.session.commit()

    def delete_comment(self, comment_id):
        comment = self.get_comment(comment_id)
        db.session.delete(comment)
        db.session.commit()

    def get_comment(self, comment_id):
        match = [
            comment for comment in self.comments if comment.id == comment_id
        ]
        if not match:
            raise Exception('Comment not found.')
        return match[0]

    def __repr__(self):
        return "<Timepoint {}>".format(self.name)

    def __str__(self):
        return self.name


class TimepointComment(db.Model):
    __tablename__ = 'timepoint_comments'

    id = db.Column('id', db.Integer, primary_key=True)
    timepoint_id = db.Column('timepoint',
                             db.String(64),
                             db.ForeignKey('timepoints.name'),
                             nullable=False)
    user_id = db.Column('user_id',
                        db.Integer,
                        db.ForeignKey('users.id'),
                        nullable=False)
    _timestamp = db.Column('comment_timestamp',
                           db.DateTime(timezone=True),
                           nullable=False)
    comment = db.Column('comment', db.Text, nullable=False)
    modified = db.Column('modified', db.Boolean, nullable=False, default=False)

    user = db.relationship('User',
                           uselist=False,
                           back_populates='timepoint_comments')
    timepoint = db.relationship('Timepoint',
                                uselist=False,
                                back_populates='comments')

    def __init__(self, timepoint_id, user_id, comment):
        self.timepoint_id = timepoint_id
        self.user_id = user_id
        self.comment = comment
        self._timestamp = datetime.datetime.now(
            FixedOffsetTimezone(offset=TZ_OFFSET))

    def update(self, new_text):
        self.comment = new_text
        self.modified = True
        db.session.add(self)
        db.session.commit()

    @property
    def timestamp(self):
        return self._timestamp.strftime('%I:%M %p, %Y-%m-%d')

    def __repr__(self):
        return "<TimepointComment for {} by user {}>".format(
            self.timepoint_id, self.user_id)


class Session(TableMixin, db.Model):
    __tablename__ = 'sessions'

    name = db.Column('name',
                     db.String(64),
                     db.ForeignKey('timepoints.name'),
                     primary_key=True)
    num = db.Column('num', db.Integer, primary_key=True)
    date = db.Column('date', db.DateTime)
    kcni_name = db.Column('kcni_name', db.String(48))
    signed_off = db.Column('signed_off', db.Boolean, default=False)
    reviewer_id = db.Column('reviewer', db.Integer, db.ForeignKey('users.id'))
    review_date = db.Column('review_date', db.DateTime(timezone=True))
    tech_notes = db.Column('tech_notes', db.String(1028))

    reviewer = db.relationship('User',
                               uselist=False,
                               back_populates='sessions_reviewed')
    timepoint = db.relationship('Timepoint',
                                uselist=False,
                                back_populates='sessions')
    scans = db.relationship('Scan',
                            cascade='all, delete',
                            order_by="Scan.series")
    empty_session = db.relationship('EmptySession',
                                    uselist=False,
                                    back_populates='session',
                                    cascade='all, delete')
    redcap_record = db.relationship('SessionRedcap',
                                    back_populates='session',
                                    uselist=False,
                                    cascade='all, delete')
    task_files = db.relationship('TaskFile', cascade='all, delete')

    def __init__(self,
                 name,
                 num,
                 date=None,
                 signed_off=False,
                 reviewer_id=None,
                 review_date=None):
        self.name = name
        self.num = num
        self.date = date
        self.signed_off = signed_off
        self.reviewer_id = reviewer_id
        self.review_date = review_date

    @property
    def site(self):
        return self.timepoint.site

    def get_study(self, study_id=None):
        return self.timepoint.get_study(study_id=study_id)

    def add_scan(self, name, series, tag, description=None, source_id=None):
        scan = Scan(name, self.name, self.num, series, tag, description,
                    source_id)
        self.scans.append(scan)
        try:
            db.session.add(self)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to add scan {}. Reason: "
                                       "{}".format(name, e))
        return scan

    def delete_scan(self, name):
        match = [scan for scan in self.scans if scan.name == name]
        if not match:
            return
        try:
            db.session.delete(match[0])
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            e.message = "Could not delete scan {}. Reason: {}".format(
                name, e.message)
            raise e

    def add_redcap(self, record_num, date, project=None, url=None,
                   instrument=None, config=None, rc_user=None, comment=None,
                   event_id=None, redcap_version=None):

        cfg = RedcapConfig.get_config(
            config_id=config, project=project, instrument=instrument, url=url,
            create=True
        )

        if self.redcap_record:
            rc_record = self.redcap_record.record
            if rc_record is None:
                raise InvalidDataException(
                    "{} has been manually marked as not expecting a Redcap "
                    "record. Failed to add record ({}, {}, {}, {}, {})".format(
                        self, record_num, project, url, instrument, date))
            if (str(rc_record.record) != str(record_num) or
                    rc_record.config.id != cfg.id or
                    str(rc_record.date) != str(date)):
                raise InvalidDataException("Existing record already found. "
                                           "Please remove the old record "
                                           "before adding a new one.")
        else:
            rc_record = RedcapRecord(record_num, cfg.id, date, redcap_version)
            db.session.add(rc_record)
            # Flush to get an ID assigned
            db.session.flush()

            self.redcap_record = SessionRedcap(
                self.name, self.num, rc_record.id)
            self.save()

        if rc_user:
            rc_record.user = rc_user
        if comment:
            rc_record.comment = comment
        if event_id:
            rc_record.event_id = event_id

        try:
            self.save()
        except IntegrityError as e:
            logger.error("Can't update redcap record {}. Reason: {}".format(
                rc_record.id, e))
            db.session.rollback()
        except Exception as e:
            logger.error("Unable to save redcap record {} for {} to database. "
                         "Reason: {}".format(rc_record.record, self, e))
            db.session.rollback()
        return rc_record

    def is_qcd(self):
        if self.timepoint.is_phantom:
            return True
        return self.signed_off

    def missing_scans(self):
        if self.redcap_record and not self.scans and not self.empty_session:
            return True
        return False

    def sign_off(self, user_id):
        self.signed_off = True
        self.reviewer_id = user_id
        self.review_date = datetime.datetime.now(
            FixedOffsetTimezone(offset=TZ_OFFSET))
        db.session.add(self)
        db.session.commit()

    def is_new(self):
        return ((self.scans is None and self.missing_scans())
                or any([scan.is_new() for scan in self.scans]))

    def get_blacklist_entries(self):
        """
        Returns all ScanChecklist entries for all blacklisted scans in this
        session.
        """
        entries = []
        for scan in self.scans:
            if not scan.blacklisted():
                continue
            entries.append(scan.get_checklist_entry())
        return entries

    def delete(self):
        """
        This will also delete anything referencing the current session (i.e.
        any scans, redcap comments, blacklist entries or dismissed 'missing
        scans' errors)
        """
        if (self.redcap_record and
                self.redcap_record.record and
                not self.redcap_record.record.is_shared):
            # Without this, deletes wont propagate correctly to RedcapRecord
            # and you end up with orphaned records
            db.session.delete(self.redcap_record.record)
        db.session.delete(self)
        db.session.commit()

    def add_task(self, file_path, name=None):
        for item in self.task_files:
            if file_path == item.file_path:
                return item
        new_task = TaskFile(self.name, self.num, file_path, file_name=name)
        self.task_files.append(new_task)
        try:
            self.save()
        except Exception as e:
            logger.error("Unable to add task file {}. Reason: {}".format(
                file_path, e))
            db.session.rollback()
            return None
        return new_task

    def expects_notes(self, study=None):
        study = self.get_study(study)
        study_site = study.sites[self.site.name]
        return study_site.uses_notes

    def get_expected_scans(self, study_id=None):
        study = self.get_study(study_id)
        return study.get_tag_counts(self.site.name, self.timepoint.is_phantom)

    def __repr__(self):
        return "<Session {}, {}>".format(self.name, self.num)

    def __str__(self):
        return "{}_{:02}".format(self.name, self.num)


class EmptySession(db.Model):
    """
    This table exists solely so QCers can dismiss errors about empty sessions
    and comment on any follow up they've performed.
    """
    __tablename__ = 'empty_sessions'

    name = db.Column('name', db.String(64), primary_key=True, nullable=False)
    num = db.Column('num', db.Integer, primary_key=True, nullable=False)
    comment = db.Column('comment', db.String(2048), nullable=False)
    user_id = db.Column('reviewer',
                        db.Integer,
                        db.ForeignKey('users.id'),
                        nullable=False)
    date_added = db.Column('date_added', db.DateTime(timezone=True))

    session = db.relationship('Session',
                              uselist=False,
                              back_populates='empty_session')
    reviewer = db.relationship('User', uselist=False, lazy='joined')

    __table_args__ = (ForeignKeyConstraint(
        ['name', 'num'], ['sessions.name', 'sessions.num']), )

    def __init__(self, name, num, user_id, comment):
        self.name = name
        self.num = num
        self.user_id = user_id
        self.comment = comment
        self.date_added = datetime.datetime.now(
            FixedOffsetTimezone(offset=TZ_OFFSET))

    def __repr__(self):
        return "<EmptySession {}, {}>".format(self.name, self.num)


class SessionRedcap(db.Model):
    # Using a class instead of an association table here to let us know when an
    # entry has been added without a redcap record (i.e. when a user has let us
    # know that a session is never going to get a redcap record)
    __tablename__ = 'session_redcap'

    name = db.Column('name', db.String(64), primary_key=True, nullable=False)
    num = db.Column('num', db.Integer, primary_key=True, nullable=False)
    record_id = db.Column('record_id', db.Integer,
                          db.ForeignKey('redcap_records.id'))

    session = db.relationship('Session',
                              back_populates='redcap_record',
                              uselist=False)
    record = db.relationship('RedcapRecord',
                             back_populates='sessions',
                             uselist=False)

    __table_args__ = (ForeignKeyConstraint(
        ['name', 'num'], ['sessions.name', 'sessions.num']), )

    def __init__(self, name, num, record_id=None):
        self.name = name
        self.num = num
        self.record_id = record_id

    def share_record(self, target_session):
        """
        Shares an existing redcap record with another session that represents
        an alternate ID for the original participant
        """
        target_session.redcap_record = SessionRedcap(target_session.name,
                                                     target_session.num,
                                                     self.record_id)
        db.session.add(target_session)
        try:
            db.session.commit()
        except Exception:
            raise InvalidDataException("Failed to share redcap record {} with "
                                       "session {}".format(
                                           self.record_id, target_session))
            return None
        return target_session.redcap_record

    def __repr__(self):
        return "<SessionRedcap {}, {} - record {}>".format(
            self.name, self.num, self.record_id)


class Scan(TableMixin, db.Model):
    __tablename__ = 'scans'

    id = db.Column('id', db.Integer, primary_key=True)
    name = db.Column('name', db.String(128), nullable=False)
    bids_name = db.Column('bids_name', db.Text)
    timepoint = db.Column('timepoint', db.String(64), nullable=False)
    repeat = db.Column('session', db.Integer, nullable=False)
    series = db.Column('series', db.Integer, nullable=False)
    tag = db.Column('tag',
                    db.String(64),
                    db.ForeignKey('scantypes.tag'),
                    nullable=False)
    description = db.Column('description', db.String(128))
    length = db.Column('length', db.String(10), nullable=True)
    conv_errors = db.Column('conversion_errors', db.Text)
    json_path = db.Column('json_path', db.String(1028))
    json_contents = db.Column('json_contents', JSONB)
    json_created = db.Column('json_created', db.DateTime(timezone=True))
    # If a scan is a link, this will hold the id of the source scan
    source_id = db.Column('source_data', db.Integer, db.ForeignKey(id))

    # If a scan has any symbolic links pointing to it 'links' will be a list
    # of them. If a scan is just a link pointing to some other data
    # 'source_data' will point to this original data.
    links = db.relationship('Scan',
                            cascade='all, delete',
                            backref=db.backref('source_data',
                                               remote_side=[id]))
    qc_review = db.relationship('ScanChecklist',
                                uselist=False,
                                back_populates='scan',
                                cascade='all, delete',
                                lazy='joined')
    session = db.relationship('Session', uselist=False, back_populates='scans')
    scantype = db.relationship('Scantype',
                               uselist=False,
                               back_populates='scans')
    analysis_comments = db.relationship('AnalysisComment',
                                        cascade='all, delete')
    metric_values = db.relationship('MetricValue',
                                    cascade='all, delete-orphan')
    header_diffs = db.relationship(
        'ScanGoldStandard',
        cascade='all, delete',
        order_by='desc(ScanGoldStandard.date_added)',
        back_populates='scan')

    __table_args__ = (ForeignKeyConstraint(['timepoint', 'session'],
                                           ['sessions.name', 'sessions.num']),
                      UniqueConstraint(name))

    def __init__(self,
                 name,
                 timepoint,
                 repeat,
                 series,
                 tag,
                 description=None,
                 source_id=None):
        self.name = name
        self.timepoint = timepoint
        self.repeat = repeat
        self.series = series
        self.tag = tag
        self.description = description
        self.source_id = source_id

    def add_bids(self, name):
        self.bids_name = name
        try:
            db.session.add(self)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to add bids name {} to scan "
                                       "{}. Reason: {}".format(
                                           name, self.id, e))

    def get_study(self, study_id=None):
        return self.session.get_study(study_id=study_id)

    def get_checklist_entry(self):
        if self.is_linked():
            checklist = self.source_data.qc_review
        else:
            checklist = self.qc_review
        return checklist

    def _new_checklist_entry(self, signing_user):
        if self.is_linked():
            return ScanChecklist(self.source_id, signing_user)
        return ScanChecklist(self.id, signing_user)

    def add_checklist_entry(self, signing_user, comment=None, sign_off=None):
        checklist = self.get_checklist_entry()
        if not checklist:
            checklist = self._new_checklist_entry(signing_user)
        checklist.update_entry(signing_user, comment, sign_off)
        checklist.save()
        if current_app.config.get('XNAT_ENABLED'):
            utils.update_xnat_usability(self, current_app.config)
        return checklist

    def is_linked(self):
        return self.source_id is not None

    def is_new(self):
        checklist = self.get_checklist_entry()
        return checklist is None or (not checklist.comment
                                     and not checklist.approved)

    def signed_off(self):
        checklist = self.get_checklist_entry()
        return checklist is not None and (checklist.approved
                                          and not checklist.comment)

    def flagged(self):
        checklist = self.get_checklist_entry()
        return checklist is not None and (checklist.approved
                                          and checklist.comment is not None)

    def blacklisted(self):
        checklist = self.get_checklist_entry()
        return checklist is not None and (checklist.comment is not None
                                          and not checklist.approved)

    def get_comment(self):
        checklist = self.get_checklist_entry()
        if checklist is None:
            return ""
        return checklist.comment or ""

    def list_children(self):
        return [link.name for link in self.links]

    @property
    def gold_standards(self):
        found_standards = GoldStandard.query.filter(
            GoldStandard.study == self.session.get_study().id).filter(
                GoldStandard.site == self.session.timepoint.site_id).filter(
                    GoldStandard.tag == self.tag).order_by(
                        GoldStandard.json_created.desc())
        return found_standards.all()

    @property
    def active_gold_standard(self):
        if self.header_diffs:
            return self.header_diffs[0].gold_standard

        try:
            gs = self.gold_standards[0]
        except IndexError:
            return None

        return gs

    def update_header_diffs(self, standard=None, ignore=None, tolerance=None):
        if not self.json_contents:
            raise InvalidDataException("No JSON data found for series {}"
                                       "".format(self.name))
        if standard:
            if type(standard) != GoldStandard:
                raise InvalidDataException("Must be given a "
                                           "'dashboard.models.GoldStandard' "
                                           "instance")
            gs = standard
        else:
            gs = self.active_gold_standard

        if not gs:
            raise InvalidDataException("No gold standard available for "
                                       "comparison")

        diffs = header_checks.compare_headers(self.json_contents,
                                              gs.json_contents,
                                              ignore=ignore,
                                              tolerance=tolerance)
        if self.scantype.qc_type == 'dti':
            result = header_checks.check_bvals(self.json_path, gs.json_path)
            if result:
                diffs['bvals'] = result

        found = []
        if self.header_diffs:
            found = [
                item for item in self.header_diffs
                if item.gold_standard.id == gs.id
            ]
            if found:
                new_diffs = found[0]
                new_diffs.diffs = diffs

        if not found:
            new_diffs = ScanGoldStandard(
                self.id,
                gs.id,
                diffs,
                gold_version=utils.get_software_version(gs.json_contents),
                scan_version=utils.get_software_version(self.json_contents))
        try:
            db.session.add(new_diffs)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to update header diffs for {}. "
                                       "Reason: {}".format(self, e))
        return new_diffs

    def get_header_diffs(self):
        if not self.header_diffs:
            return {}
        return self.header_diffs[0].diffs

    def is_outdated_header_diffs(self):
        """Reports whether an update to the header diffs is needed.
        """
        if not self.gold_standards:
            return False
        if not self.json_contents:
            return False
        if not self.header_diffs:
            return True
        return (
            self.header_diffs[0].gold_standard_id != self.gold_standards[0].id
        )

    def add_json(self, json_file, timestamp=None):
        self.json_contents = utils.read_json(json_file)
        self.json_path = json_file

        if timestamp:
            self.json_created = timestamp
        else:
            self.json_created = utils.file_timestamp(json_file)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to update scan {} json "
                                       "contents from file {}. Reason: "
                                       "{}".format(self, json_file, e))

    def add_error(self, error_message):
        if isinstance(error_message, list):
            error_message = "\n".join(error_message)
        self.conv_errors = error_message
        try:
            self.save()
        except Exception as e:
            db.session.rollback()
            raise InvalidDataException("Failed to add conversion error "
                                       "message for {}. Reason: {}".format(
                                           self, e))

    @property
    def qc_type(self):
        if self.session.timepoint.is_phantom:
            return self.scantype.pha_type or self.scantype.qc_type
        return self.scantype.qc_type

    def __repr__(self):
        if self.source_id:
            repr = "<Scan {}: {} link to scan {}>".format(
                self.id, self.name, self.source_id)
        else:
            repr = "<Scan {}: {}>".format(self.id, self.name)
        return repr

    def __str__(self):
        return self.name


class ScanChecklist(TableMixin, db.Model):
    __tablename__ = 'scan_checklist'

    id = db.Column('id', db.Integer, primary_key=True)
    scan_id = db.Column('scan_id',
                        db.Integer,
                        db.ForeignKey('scans.id'),
                        nullable=False)
    user_id = db.Column('user_id',
                        db.Integer,
                        db.ForeignKey('users.id'),
                        nullable=False)
    _timestamp = db.Column('review_timestamp', db.DateTime(timezone=True))
    comment = db.Column('comment', db.String(1028))
    approved = db.Column('signed_off',
                         db.Boolean,
                         nullable=False,
                         default=False)

    scan = db.relationship('Scan', uselist=False, back_populates='qc_review')
    user = db.relationship('User',
                           uselist=False,
                           back_populates='scan_comments')

    __table_args__ = (UniqueConstraint(scan_id), )

    def __init__(self, scan_id, user_id, comment=None, approved=False):
        self.scan_id = scan_id
        self.user_id = user_id
        self.comment = comment
        self.approved = approved

    @property
    def timestamp(self):
        return self._timestamp.strftime('%I:%M %p, %Y-%m-%d')

    def update_entry(self, user_id, comment=None, status=None):
        if status is not None:
            self.approved = status
        if comment is not None:
            self.comment = comment
        self.user_id = user_id
        self._timestamp = datetime.datetime.now(
            FixedOffsetTimezone(offset=TZ_OFFSET))

    def __repr__(self):
        return "<ScanChecklist for {} by user {}>".format(
            self.scan_id, self.user_id)


class ExpectedScan(TableMixin, db.Model):
    __tablename__ = 'expected_scans'

    study_id = db.Column('study', db.String(32), primary_key=True)
    site_id = db.Column('site', db.String(32), primary_key=True)
    scantype_id = db.Column('scantype', db.String(64), primary_key=True)
    count = db.Column('num_expected', db.Integer, default=0)
    pha_count = db.Column('pha_num_expected', db.Integer, default=0)

    scantype = db.relationship('Scantype', back_populates='expected_scans')
    standards = db.relationship(
        'GoldStandard',
        back_populates='expected_scan',
        cascade='all, delete'
    )

    __table_args__ = (
        ForeignKeyConstraint(['study'], ['studies.id'],
                             name='expected_scans_study_fkey'),
        ForeignKeyConstraint(['site'], ['sites.name'],
                             name='expected_scans_site_fkey'),
        ForeignKeyConstraint(['scantype'], ['scantypes.tag'],
                             name='expected_scans_scantype_fkey'),
        ForeignKeyConstraint(
            ['study', 'site'],
            ['study_sites.study', 'study_sites.site'],
            name='expected_scans_allowed_sites_fkey'
        ),
    )

    def __init__(self, study, site, scantype, count=0, pha_count=0):
        self.study_id = study
        self.site_id = site
        self.scantype_id = scantype
        self.count = count
        self.pha_count = pha_count

    def __repr__(self):
        return "<ExpectedScan {}-{}: {}>".format(
            self.study_id, self.site_id, self.scantype_id)


class Scantype(TableMixin, db.Model):
    __tablename__ = 'scantypes'

    tag = db.Column('tag', db.String(64), primary_key=True)
    qc_type = db.Column('qc_type', db.String(64))
    pha_type = db.Column('pha_type', db.String(64))

    scans = db.relationship(
        'Scan',
        back_populates='scantype',
        cascade="all, delete"
    )
    metrictypes = db.relationship(
        'Metrictype',
        back_populates='scantype',
        cascade="all, delete"
    )
    expected_scans = db.relationship(
        'ExpectedScan',
        back_populates='scantype',
        cascade='all, delete'
    )
    # viewonly=True to avoid breaking delete cascade through expected_scans
    studies = db.relationship(
        'Study',
        secondary='expected_scans',
        viewonly=True
    )

    def __init__(self, tag):
        self.tag = tag

    def __repr__(self):
        return "<Scantype {}>".format(self.tag)


class GoldStandard(db.Model):
    __tablename__ = 'gold_standards'

    id = db.Column('id', db.Integer, primary_key=True)
    study = db.Column('study', db.String(32), nullable=False)
    site = db.Column('site', db.String(32), nullable=False)
    tag = db.Column('scantype', db.String(64), nullable=False)
    json_created = db.Column('added', db.DateTime(timezone=True))
    json_contents = db.Column('contents', JSONB)
    json_path = db.Column('json_path', db.String(1028))

    scans = association_proxy('scan_gold_standard', 'scan')
    expected_scan = db.relationship('ExpectedScan', back_populates='standards')

    __table_args__ = (
        ForeignKeyConstraint(
            ['study', 'site', 'scantype'],
            ['expected_scans.study', 'expected_scans.site',
             'expected_scans.scantype'],
            name='gold_standards_expected_scan_fkey',
        ),
        UniqueConstraint(json_path, json_contents)
    )

    def __init__(self, study, gs_json):
        try:
            ident, tag, _, _ = scanid.parse_filename(gs_json)
        except scanid.ParseException:
            raise InvalidDataException("Can't parse site and scan tag info "
                                       "from gold standard file name. Please "
                                       "provide a datman named file")
        self.study = study
        self.site = ident.site
        self.tag = tag
        self.json_created = utils.file_timestamp(gs_json)
        self.json_contents = utils.read_json(gs_json)
        self.json_path = gs_json

    def __repr__(self):
        return "<GoldStandard {} for {}, {} - {}>".format(
            self.id, self.study, self.site, self.tag)

    def __str__(self):
        return os.path.basename(self.json_path)


class RedcapRecord(db.Model):
    __tablename__ = 'redcap_records'

    id = db.Column('id', db.Integer, primary_key=True)
    form_config = db.Column(
        'config', db.Integer, db.ForeignKey('redcap_config.id'),
        nullable=False
    )
    record = db.Column('record', db.String(256), nullable=False)
    date = db.Column('entry_date', db.Date, nullable=False)
    user = db.Column('redcap_user', db.Integer)
    comment = db.Column('comment', db.Text)
    event_id = db.Column('event_id', db.Integer)

    sessions = db.relationship('SessionRedcap', back_populates='record')
    config = db.relationship(
        'RedcapConfig', back_populates='records', uselist=False
    )

    __table_args__ = (UniqueConstraint(
        record,
        form_config,
        event_id,
        date,
        name='redcap_records_unique_record'), )

    def __init__(self, record, config_id, date, redcap_version=None):
        self.record = record
        self.form_config = config_id
        self.date = date
        if redcap_version:
            # Add to session to populate the config, or setting version fails
            db.session.add(self)
            db.session.flush()
            self.redcap_version = redcap_version

    @property
    def url(self):
        return self.config.url

    @property
    def project(self):
        return self.config.project

    @property
    def instrument(self):
        return self.config.instrument

    @property
    def redcap_version(self):
        return self.config.redcap_version

    @redcap_version.setter
    def redcap_version(self, value):
        self.config.redcap_version = value

    @property
    def is_shared(self):
        return len(self.sessions) > 1

    def __repr__(self):
        return "<RedcapRecord {}: record {}>".format(self.id, self.record)


class RedcapConfig(TableMixin, db.Model):
    __tablename__ = "redcap_config"

    id = db.Column(db.Integer, primary_key=True)
    project = db.Column('project_id', db.Integer, nullable=False)
    instrument = db.Column('instrument', db.String(1024), nullable=False)
    url = db.Column('url', db.String(1024), nullable=False)
    redcap_version = db.Column(
        'redcap_version', db.String(10), default='7.4.2'
    )
    date_field = db.Column('date_field', db.String(128))
    comment_field = db.Column('comment_field', db.String(128))
    user_id_field = db.Column('user_id_field', db.String(128))
    session_id_field = db.Column('session_id_field', db.String(128))
    completed_field = db.Column('completed_form_field', db.String(128))
    _completed_value = db.Column('completed_value', db.String(10))
    event_ids = db.Column('event_ids', JSONB)
    token = db.Column('token', db.String(64))

    records = db.relationship('RedcapRecord', back_populates='config')

    def __init__(self, project, instrument, url, version=None):
        self.project = project
        self.instrument = instrument
        self.url = url
        self.redcap_version = version

    @property
    def completed_value(self):
        return self._completed_value.split(",")

    @completed_value.setter
    def completed_value(self, user_value):
        if '__iter__' not in dir(user_value):
            user_value = [user_value]
        self._completed_value = ",".join([str(item) for item in user_value])

    def get_config(config_id=None, project=None, instrument=None, url=None,
                   version=None, create=False):
        if config_id:
            found = db.session.get(RedcapConfig, config_id)
            cfg = [found] if found else []
        elif project and url and instrument:
            cfg = RedcapConfig.query \
                .filter(RedcapConfig.project == project) \
                .filter(RedcapConfig.url == url) \
                .filter(RedcapConfig.instrument == instrument) \
                .all()
        else:
            cfg = []

        if len(cfg) == 1:
            return cfg[0]

        if not create:
            raise InvalidDataException("Can't locate Redcap config.")

        if not (project and url and instrument):
            raise InvalidDataException(
                "Can't create new RedCap config without project, "
                "instrument, and url."
            )

        cfg = RedcapConfig(project, instrument, url, version=version)
        cfg.save()
        return cfg

    def __repr__(self):
        return "<RedcapConfig {}>".format(self.id)


class Analysis(db.Model):
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(4096), nullable=False)
    software = db.Column(db.String(4096))

    analysis_comments = db.relationship('AnalysisComment')

    def __repr__(self):
        return ('<Analysis {}: {}>'.format(self.id, self.name))


class Metrictype(db.Model):
    __tablename__ = 'metrictypes'

    id = db.Column('id', db.Integer, primary_key=True)
    name = db.Column('name', db.String(64), nullable=False)
    scantype_id = db.Column('scantype',
                            db.String(64),
                            db.ForeignKey('scantypes.tag'),
                            nullable=False)

    scantype = db.relationship('Scantype', back_populates='metrictypes')
    metric_values = db.relationship('MetricValue')

    def __repr__(self):
        return ('<MetricType {}>'.format(self.name))


class TaskFile(db.Model):
    __tablename__ = 'session_tasks'

    id = db.Column('id', db.Integer, primary_key=True)
    timepoint = db.Column('timepoint', db.String(64), nullable=False)
    repeat = db.Column('repeat', db.Integer, nullable=False)
    file_name = db.Column('task_fname', db.String(256), nullable=False)
    file_path = db.Column('task_file_path', db.String(2048), nullable=False)

    session = db.relationship('Session',
                              uselist=False,
                              back_populates='task_files')

    __table_args__ = (ForeignKeyConstraint(['timepoint', 'repeat'],
                                           ['sessions.name', 'sessions.num']),
                      UniqueConstraint(file_path))

    def __init__(self, timepoint, repeat, file_path, file_name=None):
        self.timepoint = timepoint
        self.repeat = repeat
        self.file_path = file_path
        if not file_name:
            self.file_name = os.path.basename(self.file_path)
        else:
            self.file_name = file_name

    def __repr__(self):
        return "<TaskFile {}>".format(self.file_path)


###############################################################################
# Association Objects (i.e. many to many relationships with attributes/columns
# of their own).


class StudyUser(db.Model):
    __tablename__ = 'study_users'

    # This primary key will never be used anywhere but is needed because
    # sqlalchemy demands a primary key and the other columns cant be used
    id = db.Column('id', db.Integer, primary_key=True)
    user_id = db.Column('user_id',
                        db.Integer,
                        db.ForeignKey('users.id'),
                        nullable=False)
    study_id = db.Column('study', db.String(32), nullable=False)
    site_id = db.Column('site', db.String(32))
    is_admin = db.Column('is_admin', db.Boolean, default=False)
    primary_contact = db.Column('primary_contact', db.Boolean, default=False)
    kimel_contact = db.Column('kimel_contact', db.Boolean, default=False)
    study_RA = db.Column('study_ra', db.Boolean, default=False)
    does_qc = db.Column('does_qc', db.Boolean, default=False)

    study = db.relationship(
        'Study',
        primaryjoin='StudyUser.study_id==StudySite.study_id',
        secondary='study_sites',
        secondaryjoin='StudySite.study_id==Study.id',
        uselist=False,
        viewonly=True)
    user = db.relationship('User', back_populates='studies', viewonly=True)

    __table_args__ = (
        UniqueConstraint('study', 'user_id', 'site'),
        ForeignKeyConstraint(['study', 'site'],
                             ['study_sites.study', 'study_sites.site']),
    )

    def __init__(self,
                 study_id,
                 user_id,
                 site_id=None,
                 admin=False,
                 is_primary_contact=False,
                 is_kimel_contact=False,
                 is_study_RA=False,
                 does_qc=False):
        self.study_id = study_id
        self.user_id = user_id
        self.site_id = site_id
        self.is_admin = admin
        self.primary_contact = is_primary_contact
        self.kimel_contact = is_kimel_contact
        self.study_RA = is_study_RA
        self.does_qc = does_qc

    def __repr__(self):
        if self.site_id:
            site = self.site_id
        else:
            site = 'ALL'
        return "<StudyUser {} - {} User: {}>".format(self.study_id, site,
                                                     self.user_id)


class StudySite(TableMixin, db.Model):
    __tablename__ = 'study_sites'

    study_id = db.Column('study',
                         db.String(32),
                         db.ForeignKey('studies.id'),
                         primary_key=True)
    site_id = db.Column('site',
                        db.String(32),
                        db.ForeignKey('sites.name'),
                        primary_key=True)
    uses_redcap = db.Column('uses_redcap', db.Boolean, default=False)
    uses_notes = db.Column('uses_tech_notes', db.Boolean, default=False)
    code = db.Column('code', db.String(32))
    download_script = db.Column('download_script', db.String(128))
    post_download_script = db.Column('post_download_script', db.String(128))
    xnat_url = db.Column('xnat_url', db.String(128))
    xnat_archive = db.Column('xnat_archive', db.String(32))
    xnat_convention = db.Column(
        'xnat_convention', db.String(10), server_default='KCNI'
    )
    xnat_credentials = db.Column('xnat_credentials', db.String(128))

    # Need to specify the terms of the join to ensure users with
    # access to all sites dont get left out of the list for a specific site
    users = db.relationship(
        'StudyUser',
        primaryjoin='and_(StudySite.study_id==StudyUser.study_id,'
        'or_(StudySite.site_id==StudyUser.site_id,'
        'StudyUser.site_id==None))',
        cascade='all, delete')
    site = db.relationship('Site', back_populates='studies')
    study = db.relationship('Study', back_populates='sites')
    alt_codes = db.relationship('AltStudyCode',
                                back_populates='study_site',
                                cascade='all, delete',
                                lazy='joined')
    expected_scans = db.relationship('ExpectedScan', cascade="all, delete")

    __table_args__ = (UniqueConstraint(study_id, site_id), )

    def __init__(self, study_id, site_id, uses_redcap=False, uses_notes=None,
                 code=None):
        self.study_id = study_id
        self.site_id = site_id
        self.uses_redcap = uses_redcap
        self.uses_notes = uses_notes
        self.code = code

    def __repr__(self):
        return "<StudySite {} - {}>".format(self.study_id, self.site_id)


class StudyPipeline(TableMixin, db.Model):
    """Define QC pipelines enabled for a study.
    """
    study_id = db.Column('study',
                         db.String(32),
                         db.ForeignKey('studies.id'),
                         primary_key=True)
    pipeline_id = db.Column('pipeline_key',
                            db.String,
                            primary_key=True)
    view = db.Column('view',
                     db.String,
                     nullable=False)
    name = db.Column('name',
                     db.String,
                     nullable=False)
    scope = db.Column('scope',
                      db.ForeignKey('pipeline_scope.scope'),
                      nullable=False)

    __table_args__ = (UniqueConstraint(study_id, pipeline_id), )

    def __repr__(self):
        return f'<StudyPipeline {self.study_id} - {self.pipeline_id}>'


class PipelineScope(db.Model):
    scope = db.Column('scope', db.String(32), primary_key=True)

    def __repr__(self):
        return f'<PipelineScope {self.scope}>'


class AltStudyCode(db.Model):
    # stupid prelapse
    __tablename__ = 'alt_study_codes'

    # This isnt a true primary key. But that's ok,
    # it's really not meant to be queried by primary key, sqlalchemy just
    # forces it to have one
    study_id = db.Column('study', db.String(32), primary_key=True)
    site_id = db.Column('site', db.String(32), primary_key=True)
    code = db.Column('code', db.String(32), primary_key=True)

    study_site = db.relationship('StudySite',
                                 uselist=False,
                                 back_populates='alt_codes',
                                 lazy='joined')

    @property
    def site(self):
        return self.study_site.site

    @property
    def study(self):
        return self.study_site.study

    @property
    def uses_redcap(self):
        return self.study_site.uses_redcap

    __table_args__ = (ForeignKeyConstraint(
        ['study', 'site'], ['study_sites.study', 'study_sites.site']), )

    def __repr__(self):
        return "<AltStudyCode {}, {} - {}>".format(self.study_id, self.site_id,
                                                   self.code)


class ScanGoldStandard(db.Model):
    __tablename__ = 'scan_gold_standard'

    scan_id = db.Column(
        'scan',
        db.Integer,
        db.ForeignKey('scans.id'),
        primary_key=True
    )
    gold_standard_id = db.Column(
        'gold_standard',
        db.Integer,
        db.ForeignKey(
            'gold_standards.id',
            name='scan_gold_standard_gold_standard_fkey'
        ),
        primary_key=True
    )
    diffs = db.Column('header_diffs', JSONB)
    date_added = db.Column('date_added',
                           db.DateTime(timezone=True),
                           server_default=func.now())
    gold_version = db.Column('gold_version', db.String(128))
    scan_version = db.Column('scan_version', db.String(128))

    scan = db.relationship('Scan',
                           back_populates='header_diffs',
                           uselist=False)
    gold_standard = db.relationship(
        GoldStandard,
        backref=backref('scan_gold_standard', cascade="all, delete"),
    )

    def __init__(self,
                 scan_id,
                 gold_standard_id,
                 diffs,
                 gold_version,
                 scan_version,
                 timestamp=None):
        self.scan_id = scan_id
        self.gold_standard_id = gold_standard_id
        self.diffs = diffs
        self.gold_version = gold_version
        self.scan_version = scan_version
        if timestamp:
            self.date_added = timestamp

    @property
    def timestamp(self):
        return self.date_added.strftime('%I:%M %p, %Y-%m-%d')

    def __repr__(self):
        return "<HeaderDiffs for Scan {} and GS {}>".format(
            self.scan_id, self.gold_standard_id)

    def __str__(self):
        return self.__repr__()


class AnalysisComment(db.Model):
    __tablename__ = 'analysis_comments'

    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    analysis_id = db.Column(db.Integer,
                            db.ForeignKey('analyses.id'),
                            nullable=False)
    excluded = db.Column(db.Boolean, default=False)
    comment = db.Column(db.String(4096), nullable=False)

    scan = db.relationship('Scan',
                           uselist=False,
                           back_populates="analysis_comments")
    analysis = db.relationship('Analysis',
                               uselist=False,
                               back_populates="analysis_comments")
    user = db.relationship('User',
                           uselist=False,
                           back_populates="analysis_comments")

    def __repr__(self):
        return "<ScanComment {}: Analysis {} comment on scan {} by user "\
               "{}>".format(self.id, self.analysis_id, self.scan_id,
                            self.user_id)


class IncidentalFinding(db.Model):
    __tablename__ = 'incidental_findings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timepoint_id = db.Column(db.String(64),
                             db.ForeignKey('timepoints.name'),
                             nullable=False)
    description = db.Column(db.Text, nullable=False)
    timestamp = db.Column('date_reported',
                          db.DateTime(timezone=True),
                          nullable=False)

    session = db.relationship('Timepoint',
                              uselist=False,
                              back_populates="incidental_findings")
    user = db.relationship('User',
                           uselist=False,
                           back_populates="incidental_findings")

    def __init__(self, user_id, timepoint_id, description):
        self.user_id = user_id
        self.timepoint_id = timepoint_id
        self.description = description
        self.timestamp = datetime.datetime.now(
            FixedOffsetTimezone(offset=TZ_OFFSET))

    def __repr__(self):
        return "<IncidentalFinding {} for {} found by User {}>".format(
            self.id, self.timepoint_id, self.user_id)


class MetricValue(db.Model):
    __tablename__ = 'scan_metrics'

    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    metrictype_id = db.Column('metric_type',
                              db.Integer,
                              db.ForeignKey('metrictypes.id'),
                              nullable=False)
    _value = db.Column('value', db.Text)

    scan = db.relationship('Scan', back_populates="metric_values")
    metrictype = db.relationship('Metrictype', back_populates="metric_values")

    @property
    def value(self):
        """Returns the value field from the database.
        The value is stored as a string.
        If the value contains '::' character this will convert it to a list,
        otherwise it will attempt to cast to Float.
        Failing that the value is returned as a string.
        """
        if self._value is None:
            return
        value = self._value.split('::')
        try:
            value = [float(v) for v in value]
        except ValueError:
            return ''.join(value)
        if len(value) == 1:
            return value[0]
        else:
            return value

    @value.setter
    def value(self, value, delimiter=None):
        """Stores the value in the database as a string.
        If the delimiter is specified any characters matching delimiter are
        replaced with '::' for storage.
        Keyword arguments:
        [delimiter] -- optional character string that is replaced by '::' for
            database storage.
        """
        if delimiter is not None:
            try:
                value = value.replace(delimiter, '::')
            except AttributeError:
                pass
        self._value = str(value)

    def __repr__(self):
        return ('<Scan {}: Metric {}: Value {}>'.format(
            self.scan.name, self.metrictype.name, self.value))
