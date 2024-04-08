import importlib

import pytest
from mock import patch, Mock

import datman.config
import dashboard

pc = importlib.import_module("bin.parse_config")


class TestPromptUser:

    @patch("builtins.input")
    def test_true_only_when_y_given(self, mock_input):
        user_input = [
            "         ",
            "",
            "y",
            "n",
        ]

        mock_input.side_effect = lambda x: user_input.pop()

        assert pc.prompt_user("Test message") is False
        assert pc.prompt_user("Test message") is True
        assert pc.prompt_user("Test message") is False
        assert pc.prompt_user("Test message") is False

    @patch("builtins.input")
    def test_raises_runtime_error_for_unexpected_response(self, mock_input):
        mock_input.return_value = "dfgsxcvqa"
        with pytest.raises(RuntimeError):
            pc.prompt_user("Test message")


class TestUpdateTags:

    def test_tag_created_in_database_if_doesnt_already_exist(
            self, dash_db, config):
        assert dashboard.models.Scantype.query.all() == []
        pc.update_tags(config)

        updated_tags = dashboard.models.Scantype.query.all()
        assert len(updated_tags) == 1
        assert updated_tags[0].tag == "T1"

    def test_existing_tag_updated_when_config_settings_differ(
            self, dash_db, config):
        t1 = dashboard.models.Scantype("T1")
        t1.qc_type = "func"
        dash_db.session.add(t1)
        dash_db.session.commit()

        assert dashboard.models.db.session.get(
            dashboard.models.Scantype, "T1").qc_type == "func"
        pc.update_tags(config)
        assert dashboard.models.db.session.get(
            dashboard.models.Scantype, "T1").qc_type == "anat"

    def test_deletes_tag_record_if_not_defined_in_config_file(
            self, dash_db, config):
        t1 = dashboard.models.Scantype("T1")
        t2 = dashboard.models.Scantype("T2")

        for item in [t1, t2]:
            dash_db.session.add(item)
        dash_db.session.commit()

        assert dashboard.models.Scantype.query.all() == [t1, t2]

        pc.update_tags(config, delete_all=True)

        assert dashboard.models.Scantype.query.all() == [t1]

    @pytest.fixture
    def config(self):
        """A mock config with a single tag (T1) defined.
        """
        def get_key(name, site=None, ignore_defaults=False,
                    defaults_only=False):
            if name == "ExportSettings":
                return {
                    "T1": {
                        "Formats": ["nii", "dcm", "mnc"],
                        "QcType": "anat"
                    },
                }
            raise datman.config.UndefinedSetting

        config = Mock(spec=datman.config.config)
        config.get_key = get_key

        return config


class TestDeleteRecords:

    def test_nothing_deleted_when_skip_delete_flag_set(self, records):
        pc.delete_records(records, skip_delete=True)
        assert len(dashboard.models.Scantype.query.all()) == len(records)

    def test_all_given_records_deleted_when_delete_all_set(self, records):
        pc.delete_records(records, delete_all=True)
        assert len(dashboard.models.Scantype.query.all()) == 0

    def test_delete_func_used_to_delete_when_provided(self, records):
        def delete_func(x):
            if x.qc_type == "rest":
                x.delete()

        pc.delete_records(records, delete_func=delete_func, delete_all=True)
        result = dashboard.models.Scantype.query.all()

        for record in result:
            assert record.qc_type != "rest"

        for record in records:
            if record.qc_type != "rest":
                assert record in result

    @patch("builtins.input")
    @patch("bin.parse_config.prompt_user")
    def test_prompt_changed_when_message_given(
            self, mock_prompt, mock_input, records):
        mock_input.return_value = "y"

        message = "Testing prompt flag"
        pc.delete_records(records, prompt=message)
        for call in mock_prompt.call_args_list:
            assert message in call.args[0]

    @patch("builtins.input")
    def test_records_only_deleted_when_user_consents(
            self, mock_input, records):
        responses = ["n", "y"]
        mock_input.side_effect = lambda x: responses.pop()

        pc.delete_records(records)

        result = dashboard.models.Scantype.query.all()
        assert records[0] not in result
        assert records[1] in result

    @pytest.fixture
    def records(self, dash_db):
        t1 = dashboard.models.Scantype("T1")
        t1.qc_type = "anat"

        rest = dashboard.models.Scantype("REST")
        rest.qc_type = "func"

        for item in [t1, rest]:
            dash_db.session.add(item)
        dash_db.session.commit()

        assert dashboard.models.Scantype.query.all() == [t1, rest]
        return [t1, rest]


class TestUpdateSite:

    study_tag = "STU01"
    redcap = True
    notes = True
    archive_name = "STU01_CMH"
    convention = "DATMAN"

    def test_no_crash_if_config_file_site_doesnt_define_all_settings(
            self, config, db_study):
        pc.update_site(db_study, "MISSING_CONF", config)

    def test_raises_exception_when_given_site_not_in_config_files(
            self, config, db_study):
        with pytest.raises(Exception):
            pc.update_site(db_study, "BAD_SITE", config)

    def test_new_config_site_added_to_database_study(self, config, db_study):
        assert db_study.sites == {}
        pc.update_site(db_study, "CMH", config)
        assert "CMH" in db_study.sites

    def test_new_config_site_settings_all_added_to_database(
            self, config, db_study):
        assert db_study.sites == {}
        pc.update_site(db_study, "UT1", config)

        assert db_study.sites["UT1"].code == self.study_tag
        assert db_study.sites["UT1"].uses_redcap == self.redcap
        assert db_study.sites["UT1"].uses_notes == self.notes
        assert db_study.sites["UT1"].xnat_archive == self.archive_name
        assert db_study.sites["UT1"].xnat_convention == self.convention

    def test_updates_settings_in_database_when_config_file_differs(
            self, config, db_study):
        old_archive = "wrong_archive"
        db_study.update_site("CMH", xnat_archive=old_archive, create=True)
        assert db_study.sites["CMH"].xnat_archive == old_archive
        pc.update_site(db_study, "CMH", config)
        assert db_study.sites["CMH"].xnat_archive == self.archive_name

    @pytest.fixture
    def db_study(self, dash_db):
        study = dashboard.models.Study("STUDY")
        dash_db.session.add(study)
        dash_db.session.commit()
        return study

    @pytest.fixture
    def config(self):
        sites = {
            "CMH": {
                "XnatArchive": self.archive_name
            },
            "MISSING_CONF": {},
            "UT1": {
                "StudyTag": self.study_tag,
                "UsesRedcap": self.redcap,
                "UsesTechNotes": self.notes,
                "XnatArchive": self.archive_name,
                "XnatConvention": self.convention
            }
        }

        def get_key(key, site=None):
            if not site:
                raise datman.config.UndefinedSetting
            try:
                site_conf = sites[site]
            except KeyError:
                raise datman.config.ConfigException
            try:
                return site_conf[key]
            except KeyError:
                raise datman.config.UndefinedSetting

        def get_tags(tag):
            if tag == "CMH":
                return datman.config.TagInfo({})
            raise datman.config.UndefinedSetting

        config = Mock(spec=datman.config.config)
        config.get_key = get_key
        config.get_tags = get_tags
        return config


class TestUpdateExpectedScans:

    def test_no_crash_if_site_undefined_in_config(self, config, db_study):
        pc.update_expected_scans(db_study, "BADSITE", config)

    def test_no_records_made_if_site_undefined_in_config(
            self, config, db_study):
        assert dashboard.models.ExpectedScan.query.all() == []
        pc.update_expected_scans(db_study, "BADSITE", config)
        assert dashboard.models.ExpectedScan.query.all() == []

    def test_no_crash_if_no_tags_defined_for_site(self, config, db_study):
        pc.update_expected_scans(db_study, "NOTAGS", config)

    def test_no_scantypes_added_if_none_defined_in_site_config(
            self, config, db_study):
        assert "NOTAGS" not in db_study.scantypes
        pc.update_expected_scans(db_study, "NOTAGS", config)
        assert "NOTAGS" not in db_study.scantypes

    def test_deletes_db_scantype_if_not_in_site_config(self, config, db_study):
        dashboard.models.db.session.add(
            dashboard.models.ExpectedScan("STUDY", "NOTAGS", "T1")
        )
        dashboard.models.db.session.commit()

        assert len(db_study.scantypes["NOTAGS"]) == 1
        pc.update_expected_scans(db_study, "NOTAGS", config, delete_all=True)
        assert db_study.scantypes == {}

    def test_expected_scans_updated_with_tag_defined_in_config(
            self, config, db_study):
        assert db_study.scantypes == {}
        pc.update_expected_scans(db_study, "SITE1", config)
        assert "SITE1" in db_study.scantypes
        assert len(db_study.scantypes["SITE1"]) == 1
        assert db_study.scantypes["SITE1"][0].scantype_id == "T1"

    @pytest.fixture
    def db_study(self, dash_db):
        study = dashboard.models.Study("STUDY")
        dash_db.session.add(study)
        dash_db.session.add(dashboard.models.Site("SITE1"))
        dash_db.session.add(dashboard.models.StudySite("STUDY", "SITE1"))
        dash_db.session.add(dashboard.models.Site("NOTAGS"))
        dash_db.session.add(dashboard.models.StudySite("STUDY", "NOTAGS"))
        dash_db.session.add(dashboard.models.Scantype("T1"))
        dash_db.session.commit()
        return study

    @pytest.fixture
    def config(self):
        tag_settings = {
            "T1": {
                "formats": ["nii", "dcm", "mnc"],
                "qc_type": "anat",
                "bids": {"class": "anat", "modality_label": "T1w"},
                "Pattern": {"SeriesDescription": ["T1", "BRAVO"]},
                "Count": 1
            }
        }

        def get_tags(name):
            if name == "SITE1":
                return datman.config.TagInfo(tag_settings)
            if name == "NOTAGS":
                return datman.config.TagInfo({})
            raise datman.config.UndefinedSetting

        config = Mock(spec=datman.config.config)
        config.get_tags.side_effect = get_tags

        return config


class TestUpdateStudy:

    def test_no_crash_when_study_not_defined_in_config(self, config, dash_db):
        def set_study(study):
            raise datman.config.ConfigException
        config.set_study = set_study
        pc.update_study("BADSTUDY", config, skip_delete=True)

    def test_no_crash_when_no_sites_defined_in_config(self, config, dash_db):
        def get_sites():
            raise datman.config.UndefinedSetting
        config.get_sites = get_sites
        pc.update_study("SPINS", config, skip_delete=True)

    def test_site_records_deleted_if_no_longer_in_config(
            self, config, db_study):
        assert len(db_study.sites) == 2
        assert "UT2" in db_study.sites
        pc.update_study("SPINS", config, delete_all=True)
        assert len(db_study.sites) == 1
        assert "UT2" not in db_study.sites

    def test_db_study_unchanged_if_config_file_sets_DbIgnore(
            self, config, db_study):
        def get_key(key, site=None, ignore_defaults=False):
            if key in ["DbIgnore", "IsOpen"]:
                return True
            raise datman.config.UndefinedSetting
        config.get_key = get_key

        assert db_study.is_open is False
        pc.update_study("SPINS", config, skip_delete=True)
        assert db_study.is_open is False

    def test_study_is_created_in_database_if_doesnt_already_exist(
            self, config, dash_db):
        assert dashboard.models.Study.query.all() == []
        pc.update_study("SPINS", config, skip_delete=True)
        assert dashboard.models.db.session.get(
            dashboard.models.Study, "SPINS") is not None

    @patch("bin.parse_config.update_site")
    def test_updating_study_calls_update_site_for_configured_sites(
            self, mock_update, config, db_study):
        pc.update_study("SPINS", config, skip_delete=True)
        assert mock_update.call_count == len(config.get_sites())

    @pytest.fixture
    def config(self):
        def get_key(key, site=None, ignore_defaults=False,
                    defaults_only=False):
            raise datman.config.UndefinedSetting

        def get_path(path, study=None):
            raise datman.config.UndefinedSetting

        def get_tags(tag):
            if tag == "CMH":
                return datman.config.TagInfo({})
            raise datman.config.UndefinedSetting

        config = Mock(spec=datman.config.config)
        config.get_key = get_key
        config.get_path = get_path
        config.get_tags = get_tags
        config.get_sites.return_value = ["CMH"]
        return config

    @pytest.fixture
    def db_study(self, dash_db):
        study = dashboard.models.Study("SPINS")
        study.is_open = False
        dash_db.session.add(study)
        dash_db.session.commit()
        study.update_site("CMH", create=True)
        study.update_site("UT2", create=True)
        return study


class TestUpdateStudies:

    def test_no_crash_when_studies_not_defined_in_config(
            self, config, dash_db):
        def get_key(key, *args):
            raise datman.config.UndefinedSetting
        config.get_key = get_key
        pc.update_studies(config)

    def test_creates_or_updates_each_study_found_in_config(
            self, config, dash_db):
        assert len(config.get_key("Projects")) > 0
        pc.update_studies(config)
        for study in config.get_key("Projects"):
            assert dashboard.models.db.session.get(
                dashboard.models.Study, study) is not None

    def test_deletes_studies_not_defined_in_config(self, config, dash_db):
        extra_study = dashboard.models.Study("STUDY5")
        dash_db.session.add(extra_study)
        dash_db.session.commit()

        assert dashboard.models.db.session.get(
            dashboard.models.Study, "STUDY5") is not None
        pc.update_studies(config, delete_all=True)
        assert dashboard.models.db.session.get(
            dashboard.models.Study, "STUDY5") is None

    @pytest.fixture
    def config(self):
        def get_key(key, site=None, *kwargs):
            if key == "Projects":
                return {
                    "STUDY1": "study1_settings.yml",
                    "STUDY2": "study2_settings.yml",
                    "STUDY3": "study3_settings.yml"
                }
            raise datman.config.UndefinedSetting
        config = Mock(spec=datman.config.config)
        config.get_key = get_key
        config.get_sites.return_value = []
        return config
