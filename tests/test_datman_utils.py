import os
import pytest
from mock import patch, Mock
from json import JSONDecodeError

import datman
from datman.config import config
import dashboard
import dashboard.datman_utils as dm_utils

FIXTURES = "fixtures/test_datman_utils"


class TestGetManifests:

    qc_dir = os.path.join(
        os.path.split(os.path.realpath(__file__))[0],
        FIXTURES
    )

    @patch("datman.config.config")
    def test_returns_empty_dict_when_no_qc_dir_defined(
            self, mock_config, timepoint):

        def get_path(key):
            raise datman.exceptions.UndefinedSetting

        mock_conf = Mock(spec=config)
        mock_conf.get_path = get_path
        mock_config.return_value = mock_conf

        result = dm_utils.get_manifests(timepoint)
        assert result == {}

    @patch("datman.config.config")
    def test_manifests_organized_by_sessions(
            self, patch_config, config, timepoint):
        patch_config.return_value = config

        manifests = dm_utils.get_manifests(timepoint)
        assert list(manifests.keys()) == [1, 2]

    @patch("datman.config.config")
    def test_finds_all_manifests_for_each_session(
            self, patch_config, config, timepoint):
        patch_config.return_value = config

        manifests = dm_utils.get_manifests(timepoint)

        assert len(manifests[1]) == 2
        assert len(manifests[2]) == 1

    @patch("json.load")
    @patch("datman.config.config")
    def test_reports_error_when_json_unparseable(
            self, patch_config, mock_json, config, timepoint):
        patch_config.return_value = config
        mock_json.side_effect = JSONDecodeError("", "", 0)

        manifests = dm_utils.get_manifests(timepoint)

        for session in manifests:
            for scan in manifests[session]:
                json_contents = manifests[session][scan]
                assert "Error" in json_contents

    @pytest.fixture
    def config(self):

        def get_path(key):
            if key == "qc":
                return self.qc_dir
            raise datman.exceptions.UndefinedSetting

        mock_conf = Mock(spec=datman.config.config)
        mock_conf.get_path = get_path
        return mock_conf


@pytest.fixture
def timepoint(dash_db):
    """Populate the test database with some records for testing.
    """
    study = dashboard.models.Study("STUDY")
    dash_db.session.add(study)
    dash_db.session.commit()

    study.update_site("SITE", create=True)

    t1 = dashboard.models.Scantype("T1")
    dti = dashboard.models.Scantype("DTI60-1000")
    dash_db.session.add(t1)
    dash_db.session.add(dti)
    dash_db.session.commit()

    study.update_scantype("SITE", t1, num=1, create=True)
    study.update_scantype("SITE", dti, num=1, create=True)

    timepoint = dashboard.models.Timepoint("STUDY_SITE_0001_01", "SITE")
    study.add_timepoint(timepoint)
    timepoint.add_session(1)
    timepoint.add_session(2)

    timepoint.sessions[1].add_scan(
        "STUDY_SITE_0001_01_01_T1_2",
        2,
        "T1",
        "SagT1Bravo"
    )
    timepoint.sessions[1].add_scan(
        "STUDY_SITE_0001_01_01_DTI60-1000_5",
        5,
        "DTI60-1000",
        "Ax-DTI-60plus5"
    )
    timepoint.sessions[2].add_scan(
        "STUDY_SITE_0001_01_02_DTI60-1000_4",
        4,
        "DTI60-1000",
        "Ax-DTI-60plus5"
    )

    return timepoint
