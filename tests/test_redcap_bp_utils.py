import pytest
from mock import Mock, patch

import dashboard
import dashboard.blueprints.redcap.utils as rc_utils
import datman.scanid


class TestSetSession:

    def test_valid_id_returns_a_dashboard_session_record(self, records):
        name = "STU01_CMH_0001_01_01"
        session = rc_utils.set_session(name)
        assert str(session) == name

    def test_valid_id_with_space_padding_is_accepted(self, records):
        name = " STU01_CMH_0001_01_01 "
        session = rc_utils.set_session(name)
        assert session is not None
        assert str(session) == name.strip()

    def test_id_with_undefined_site_raises_exception(self, dash_db):
        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.set_session("STU01_ABC_0001_01_01")

    def test_id_with_undefined_study_raises_exception(self, dash_db):
        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.set_session("AAA00_CMH_0001_01_01")

    def test_id_with_unexpected_format_raises_exception(self, dash_db):
        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.set_session("STUDYCMH-1000")

    @pytest.fixture
    def records(self, dash_db):
        study = dashboard.models.Study("STUDY1")
        dash_db.session.add(study)
        study.update_site("CMH", code="STU01", create=True)
        return [study]


class TestGetTimepoint:

    def test_can_find_timepoint_by_datman_ident(self, study, ident):
        study.add_timepoint(ident)

        tp = rc_utils.get_timepoint(ident)

        assert tp is not None
        assert tp.name == ident.get_full_subjectid_with_timepoint()
        assert study.id in tp.studies

    def test_creates_timepoint_if_doesnt_exist(self, study, ident):
        tp = rc_utils.get_timepoint(ident)

        assert tp is not None
        assert tp.name == ident.get_full_subjectid_with_timepoint()
        assert study.id in tp.studies

    @pytest.fixture
    def study(self, dash_db):
        study = dashboard.models.Study("STUDY01")
        dash_db.session.add(study)
        study.update_site("CMH", code="STU01", create=True)
        return study

    @pytest.fixture
    def ident(self):
        return datman.scanid.parse("STU01_CMH_0001_01_01")


@patch("dashboard.blueprints.redcap.utils.monitor_scan_import")
@patch("redcap.Project")
class TestCreateFromRequest:

    record_id = "100"
    event_name = "baseline_other_arm_1"
    session = "STU01_ABC_1111_01_01"
    comment = "Scan went ok"
    date = "2022-02-10"
    pid = 9999
    instrument = "mri_scan_log"
    url = "https://fake.website.ca/redcap/"
    version = "10.0.0"
    date_field = "date"
    comment_field = "cmts"
    session_field = "par_id"
    completed_field = "mri_scan_log_complete"
    completed_value = "2"
    event_ids = {
        event_name: 12345,
        "other_event": 54321
    }
    token = "AAAAAAAAAAAAAAAAAAAAAAAAA"
    redcap_records = [{
        "redcap_event_name": event_name,
        completed_field: completed_value,
        date_field: date,
        comment_field: comment,
        session_field: session
    }]

    @pytest.fixture
    def det(self):
        det_request = Mock()
        # 'form' is the contents of a REDCap DET
        # The below fields are all fields expected in a DET for
        # version 11.1.21 and prior
        det_request.form = {
            "redcap_url": self.url,
            "project_url": f"{self.url}redcap_v{self.version}/index.php?" +
                           f"pid={self.pid}",
            "project_id": self.pid,
            "username": "redcap_user",
            "record": self.record_id,
            "redcap_event_name": self.event_name,
            "instrument": self.instrument,
            self.completed_field: self.completed_value
        }
        return det_request

    @pytest.fixture
    def records(self, dash_db):
        # Create study STUDY with site ABC
        study = dashboard.models.Study("STUDY")
        dash_db.session.add(study)
        study.update_site("ABC", code="STU01", create=True)

        # Add a timepoint and session 01
        timepoint = dashboard.models.Timepoint(self.session[:-3], "ABC")
        study.add_timepoint(timepoint)
        timepoint.add_session(1)

        # Add a redcap_config entry
        rc = dashboard.models.RedcapConfig(
            self.pid,
            self.instrument,
            self.url
        )
        rc.date_field = self.date_field
        rc.comment_field = self.comment_field
        rc.session_id_field = self.session_field
        rc.completed_field = self.completed_field
        rc.completed_value = self.completed_value
        rc.event_ids = self.event_ids
        rc.token = self.token
        dash_db.session.add(rc)
        dash_db.session.commit()

        return dash_db

    def test_raises_exception_when_malformed_request_received(
            self, mock_http, mock_monitor, det, records):
        del det.form["project_id"]
        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.create_from_request(det)

    def test_no_records_added_when_matching_redcap_config_not_found(
            self, mock_http, mock_monitor, det, records):
        det.form["project_id"] = 1111
        assert det.form["project_id"] != self.pid

        before_det = self.get_db_records()
        rc_utils.create_from_request(det)
        after_det = self.get_db_records()

        assert mock_http.call_count == 0
        for idx in range(len(before_det)):
            assert before_det[idx] == after_det[idx]

    def test_no_records_added_when_form_not_complete(
            self, mock_http, mock_monitor, det, dash_db):
        det.form[self.completed_field] = "1"

        for item in self.get_db_records():
            assert item == [], "Error - Database not empty before test ran."

        rc_utils.create_from_request(det)

        assert mock_http.call_count == 0
        for item in self.get_db_records():
            assert item == [], "Error - New data was added to database."

    def test_exception_raised_if_multiple_redcap_records_match(
            self, mock_http, mock_monitor, det, records):
        export_output = []
        export_output.extend(self.redcap_records)
        export_output.append({
            "record": self.record_id,
            "redcap_event_name": self.event_name
        })
        mock_http.return_value = self.mock_redcap_export(export_output)

        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.create_from_request(det)

    def test_exception_raised_if_record_not_found_on_server(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export([])
        with pytest.raises(dashboard.exceptions.RedcapException):
            rc_utils.create_from_request(det)

    def test_adds_redcap_record_to_session(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()
        session = dashboard.models.db.session.get(
            dashboard.models.Session, (self.session[:-3], 1))
        assert session.redcap_record is None

        rc_utils.create_from_request(det)

        assert session.redcap_record is not None
        assert session.redcap_record.record.comment == self.comment

    def test_adds_session_if_doesnt_exist(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()

        timepoint = self.session[:-3]
        session = dashboard.models.db.session.get(
            dashboard.models.Session, (timepoint, 1))
        if session:
            session.delete()
        assert dashboard.models.db.session.get(
            dashboard.models.Session, (timepoint, 1)) is None
        rc_utils.create_from_request(det)

        session = dashboard.models.db.session.get(
            dashboard.models.Session, (timepoint, 1))
        assert session is not None

    def test_updates_redcap_record_if_updates_on_server(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()

        # Add a redcap record
        rc_utils.create_from_request(det)

        # Modify the comment on the 'server'
        new_comment = "Scan was NOT ok."
        new_record = self.redcap_records[0].copy()
        new_record[self.comment_field] = new_comment
        mock_http.return_value = self.mock_redcap_export([new_record])

        # Resend the data entry trigger
        rc_utils.create_from_request(det)

        session = dashboard.models.db.session.get(
            dashboard.models.Session, (self.session[:-3], 1))
        assert session is not None
        assert session.redcap_record.record.comment == new_comment

    def test_sets_event_id_of_redcap_record(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()
        rc_utils.create_from_request(det)

        session = dashboard.models.db.session.get(
            dashboard.models.Session, (self.session[:-3], 1))
        assert session.redcap_record is not None
        db_record = session.redcap_record.record

        assert db_record.event_id == self.event_ids[self.event_name]

    def test_doesnt_fail_if_config_event_ids_not_set(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()

        # Delete the event_ids from config
        rc = dashboard.models.db.session.get(dashboard.models.RedcapConfig, 1)
        rc.event_ids = None
        dashboard.models.db.session.add(rc)
        dashboard.models.db.session.commit()

        assert rc.event_ids is None
        rc_utils.create_from_request(det)
        record = dashboard.models.db.session.get(
            dashboard.models.RedcapRecord, 1)
        assert record is not None

    def test_det_with_different_version_causes_redcap_config_version_update(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()

        redcap_config = dashboard.models.RedcapConfig.get_config(
            project=self.pid,
            instrument=self.instrument,
            url=self.url
        )
        assert redcap_config is not None
        assert redcap_config.redcap_version != self.version

        rc_utils.create_from_request(det)

        assert redcap_config.redcap_version == self.version

    def test_calls_monitor_scan_import_for_session(
            self, mock_http, mock_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()
        rc_utils.create_from_request(det)

        session = dashboard.models.db.session.get(
            dashboard.models.Session, (self.session[:-3], 1))
        mock_monitor.assert_called_once_with(session)

    @patch("dashboard.blueprints.redcap.utils.monitor_scan_download")
    def test_calls_monitor_scan_download_if_download_script_is_set(
            self, mock_download, mock_http, mock_scan_monitor, det, records):
        mock_http.return_value = self.mock_redcap_export()

        study_site = dashboard.models.db.session.get(
            dashboard.models.StudySite, ("STUDY", "ABC"))
        study_site.download_script = "/some/path/post_download.sh"
        dashboard.models.db.session.add(study_site)
        dashboard.models.db.session.commit()

        rc_utils.create_from_request(det)

        session = dashboard.models.db.session.get(
            dashboard.models.Session, (self.session[:-3], 1))
        mock_download.assert_called_once_with(session)

    def mock_redcap_export(self, records=None):
        def export_records(id_list):
            if id_list == [self.record_id]:
                if records is not None:
                    return records
                return self.redcap_records
            return []
        mock_rc = Mock()
        mock_rc.export_records = export_records
        return mock_rc

    def get_db_records(self):
        """Get all records from tables that may be modified.
        """
        return [
            dashboard.models.RedcapRecord.query.all(),
            dashboard.models.Session.query.all(),
            dashboard.models.RedcapConfig.query.all()
        ]
