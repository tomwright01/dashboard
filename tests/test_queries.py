import pytest

from tests.utils import (add_studies, add_scans, query_db, Session, Scan,
                         QcReview)
import dashboard.queries


class TestGetStudies:

    def test_finds_study_by_name(self, records):
        studies = dashboard.queries.get_studies(name="SPINS")
        assert len(studies) == 1
        assert studies[0].id == "SPINS"

    def test_finds_studies_by_tag(self, records):
        studies = dashboard.queries.get_studies(tag="SPN01")
        assert len(studies) == 1
        assert studies[0].id == "SPINS"

    def test_finds_studies_by_scan_site(self, records):
        studies = dashboard.queries.get_studies(site="CMH")
        assert len(studies) == 2

    def test_narrows_search_when_multiple_terms_given(self, records):
        studies = dashboard.queries.get_studies(tag="SPN01", site="CMH")
        assert len(studies) == 1
        assert studies[0].id == "SPINS"

    def test_all_studies_returned_if_no_args_given(self, records):
        studies = dashboard.queries.get_studies()
        assert len(studies) == 3

    def test_create_flag_makes_study_if_doesnt_exist_and_name_is_given(
            self, records):
        studies = dashboard.queries.get_studies("STUDY4", create=True)
        assert len(studies) == 1
        assert studies[0].id == "STUDY4"

    def test_create_flag_ignored_if_no_name_provided(self, records):
        studies = dashboard.queries.get_studies(tag="PRE01", create=True)
        assert not studies

    def test_find_studies_can_locate_by_alt_study_code(self, records):
        alt_code = dashboard.models.AltStudyCode()
        alt_code.study_id = "SPINS"
        alt_code.site_id = "UT1"
        alt_code.code = "SPN02"
        dashboard.models.db.session.add(alt_code)
        dashboard.models.db.session.commit()

        studies = dashboard.queries.get_studies(tag="SPN02")
        assert len(studies) == 1
        assert studies[0].id == "SPINS"

    @pytest.fixture
    def records(self, dash_db):
        study1 = dashboard.models.Study("SPINS")
        dash_db.session.add(study1)

        study1.update_site("CMH", code="SPN01", create=True)
        study1.update_site("UT1", code="SPN01", create=True)

        study2 = dashboard.models.Study("ASCEND")
        dash_db.session.add(study2)

        study2.update_site("CMH", create=True)

        study3 = dashboard.models.Study("ASDD")
        dash_db.session.add(study3)

        dash_db.session.commit()
        return [study1, study2, study3]


class TestGetScanQc:

    def test_finds_all_reviewed_human_scans_when_no_search_terms(self):
        result = dashboard.queries.get_scan_qc()
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false;"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_human_qc_except_approved_when_flag_is_false(self):
        result = dashboard.queries.get_scan_qc(approved=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND NOT (sc.signed_off = true AND sc.comment IS NULL);"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_human_qc_except_flagged_when_flag_is_false(self):
        result = dashboard.queries.get_scan_qc(flagged=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND NOT (sc.signed_off = true AND sc.comment IS NOT NULL);"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_human_qc_except_blacklisted_when_flag_is_false(self):
        result = dashboard.queries.get_scan_qc(blacklisted=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND NOT (sc.signed_off = false AND sc.comment IS NOT NULL);"
        )

        self.assert_result_matches_expected(result, expected)

    def test_can_return_only_approved_entries(self):
        result = dashboard.queries.get_scan_qc(
            blacklisted=False, flagged=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND sc.signed_off = true AND sc.comment IS NULL"
        )

        self.assert_result_matches_expected(result, expected)

    def test_can_return_only_flagged_entries(self):
        result = dashboard.queries.get_scan_qc(
            approved=False, blacklisted=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND sc.signed_off = true AND sc.comment IS NOT NULL"
        )

        self.assert_result_matches_expected(result, expected)

    def test_can_return_only_blacklisted_entries(self):
        result = dashboard.queries.get_scan_qc(
            approved=False, flagged=False)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND sc.signed_off = false AND sc.comment IS NOT NULL"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_study(self):
        result = dashboard.queries.get_scan_qc(study="STUDY1")
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t, "
            "      study_timepoints as st"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND st.timepoint = t.name"
            "      AND t.is_phantom = false"
            "      AND st.study = 'STUDY1';"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_studies(self):
        result = dashboard.queries.get_scan_qc(study=["STUDY1", "STUDY3"])
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t, "
            "      study_timepoints as st"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND st.timepoint = t.name"
            "      AND t.is_phantom = false"
            "      AND st.study in ('STUDY1', 'STUDY3');"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_site(self):
        result = dashboard.queries.get_scan_qc(site="CMH")
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND t.site = 'CMH';"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_sites(self):
        result = dashboard.queries.get_scan_qc(site=["UTO", "ABC"])
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND t.site in ('UTO', 'ABC');"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_tag(self):
        result = dashboard.queries.get_scan_qc(tag="T2")
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND s.tag = 'T2';"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matching_tags(self):
        result = dashboard.queries.get_scan_qc(tag=["T1", "DTI60-1000"])
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND s.tag in ('T1', 'DTI60-1000');"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_qc_matching_provided_comment(self):
        result = dashboard.queries.get_scan_qc(comment="bad scan")
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "      AND sc.comment ilike 'bad scan';"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_qc_matching_comment_when_case_differs(self):
        result = dashboard.queries.get_scan_qc(comment="Bad Scan")
        expected = self.get_records(
            "SELECT s.name"
            " FROM scans as s, scan_checklist as sc"
            " WHERE s.id = sc.scan_id AND sc.comment ilike 'Bad Scan';"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_all_qc_matches_when_multiple_comments_given(self):
        result = dashboard.queries.get_scan_qc(comment=["meh", "bad scan"])
        expected = self.get_records(
            "SELECT s.name"
            " FROM scans as s, scan_checklist as sc"
            " WHERE s.id = sc.scan_id "
            "    AND lower(sc.comment) in ('bad scan', 'meh');"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_unreviewed_scans_when_flag_is_true(self):
        result = dashboard.queries.get_scan_qc(include_new=True)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s"
            "  JOIN timepoints as t on t.name = s.timepoint"
            "  LEFT JOIN scan_checklist as sc ON s.id = sc.scan_id"
            "  WHERE t.is_phantom = false;"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_records_for_phantoms_when_flag_is_true(self):
        result = dashboard.queries.get_scan_qc(include_phantoms=True)
        expected = self.get_records(
            "SELECT s.name"
            " FROM scans as s, scan_checklist as sc"
            " WHERE s.id = sc.scan_id;"
        )

        self.assert_result_matches_expected(result, expected)

    def test_finds_records_when_user_id_given(self):
        result = dashboard.queries.get_scan_qc(user_id=2)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t, "
            "      study_timepoints as st, study_users as su"
            "  WHERE s.id = sc.scan_id"
            "      AND sc.user_id = 2"
            "      AND sc.user_id = su.user_id"
            "      AND t.name = s.timepoint"
            "      AND st.timepoint = t.name"
            "      AND t.is_phantom = false"
            "      AND st.study = su.study"
            "      AND (su.site IS NULL OR su.site = t.site);"
        )

        self.assert_result_matches_expected(result, expected)

    def test_limits_records_based_on_user_access_rights_when_user_id_given(
            self):
        result = dashboard.queries.get_scan_qc(site=["CMH", "UTO"], user_id=1)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t, "
            "      study_timepoints as st, study_users as su"
            "  WHERE s.id = sc.scan_id"
            "      AND su.user_id = 1"
            "      AND sc.user_id = su.user_id"
            "      AND t.name = s.timepoint"
            "      AND st.timepoint = t.name"
            "      AND t.is_phantom = false"
            "      AND t.site in ('CMH', 'UTO')"
            "      AND st.study = su.study"
            "      AND (su.site IS NULL OR su.site = t.site);"
        )

        self.assert_result_matches_expected(result, expected)
        # An extra check, to confirm no UTO records are found for this user
        for item in result:
            assert "_UTO_" not in item['name']

    def test_returns_empty_list_when_user_access_rights_prevents_access(self):
        result = dashboard.queries.get_scan_qc(study=["STUDY3"], user_id=2)
        expected = self.get_records(
            "SELECT s.name"
            "  FROM scans as s, scan_checklist as sc, timepoints as t, "
            "      study_timepoints as st, study_users as su"
            "  WHERE s.id = sc.scan_id"
            "      AND su.user_id = 2"
            "      AND sc.user_id = su.user_id"
            "      AND t.name = s.timepoint"
            "      AND st.timepoint = t.name"
            "      AND t.is_phantom = false"
            "      AND st.study = 'STUDY3'"
            "      AND st.study = su.study"
            "      AND (su.site IS NULL OR su.site = t.site);"
        )

        assert result == expected == []

    def test_sorts_output_by_scan_when_flag_given(self):
        result = dashboard.queries.get_scan_qc(sort=True)
        expected = self.get_records(
            "SELECT s.name, sc.signed_off, sc.comment"
            "  FROM scans as s, scan_checklist as sc, timepoints as t"
            "  WHERE s.id = sc.scan_id"
            "      AND t.name = s.timepoint"
            "      AND t.is_phantom = false"
            "  ORDER BY s.name;"
        )

        result_names = [item['name'] for item in result]
        assert result_names == expected

    def test_returns_list_of_dicts(self):
        result = dashboard.queries.get_scan_qc()
        for item in result:
            assert isinstance(item, dict)
        for item in result:
            assert 'name' in item
            assert 'comment' in item
            assert 'approved' in item

    def get_records(self, sql_query):
        return [item[0] for item in query_db(sql_query)]

    def assert_result_matches_expected(self, result, expected):
        # Ensure there are no extra entries
        assert len(result) == len(expected)

        # Ensure every entry expected is found in the actual result
        scan_list = [item['name'] for item in result]
        for scan in expected:
            assert scan in scan_list

    @pytest.fixture(autouse=True, scope="class")
    def records(self, read_only_db):
        """Create checklist entries to search.

        The end result should be the following QC review data available to be
        searched by tests:

        ===================================  ======== ========== ========
        Scan                                 Reviewer Status     Comment
        ===================================  ======== ========== ========
        STUDY1_CMH_0001_01_01_T1_10          1        approve
        STUDY1_CMH_0001_01_01_DTI60-1000_11  1        flag       meh
        STUDY1_UTO_0002_01_01_T1_10          2        blacklist  bad scan
        STUDY1_CMH_PHA_FBN190428_T1_01       1        approve
        STUDY2_CMH_4444_01_01_T2_03          1        blacklist  corrupted
        STUDY2_CMH_4444_01_01_T2_04          2        approve
        STUDY2_CMH_4444_01_01_RST_05
        STUDY2_CMH_PHA_FBN220920_T2_01       2        blacklist  corrupted
        STUDY3_ABC_1234_01_01_DTI60-1000_11  1        approve
        """
        user1 = dashboard.models.User("Jane", "Doe")
        user2 = dashboard.models.User("John", "Doe")
        read_only_db.session.add(user1)
        read_only_db.session.add(user2)
        read_only_db.session.commit()

        studies = add_studies({
            "STUDY1": {
                "CMH": ["T1", "DTI60-1000"],
                "UTO": ["T1"]
            },
            "STUDY2": {
                "CMH": ["T2", "RST"]
            },
            "STUDY3": {
                "ABC": ["DTI60-1000"]
            }
        })

        scans = {
            "STUDY1": {
                Session("STUDY1_CMH_0001_01", "CMH", 1): [
                    Scan("STUDY1_CMH_0001_01_01_T1_10", 10, "T1",
                         QcReview(user1.id, True)),
                    Scan("STUDY1_CMH_0001_01_01_DTI60-1000_11", 11,
                         "DTI60-1000", QcReview(user1.id, True, "meh")),
                ],
                Session("STUDY1_UTO_0002_01", "UTO", 1): [
                    Scan("STUDY1_UTO_0002_01_01_T1_10", 10, "T1",
                         QcReview(user2.id, False, "bad scan")),
                ],
                Session("STUDY1_CMH_PHA_FBN190428", "CMH", 1, True): [
                    Scan("STUDY1_CMH_PHA_FBN190428_T1_01", 1, "T1",
                         QcReview(user1.id, True))
                ]
            },
            "STUDY2": {
                Session("STUDY2_CMH_4444_01", "CMH", 1): [
                    Scan("STUDY2_CMH_4444_01_01_T2_03", 3, "T2",
                         QcReview(user1.id, False, "corrupted")),
                    Scan("STUDY2_CMH_4444_01_01_T2_04", 4, "T2",
                         QcReview(user2.id, True)),
                    Scan("STUDY2_CMH_4444_01_01_RST_05", 5, "RST")
                ],
                Session("STUDY2_CMH_PHA_FBN220920", "CMH", 1, True): [
                    Scan("STUDY2_CMH_PHA_FBN220920_T2_01", 1, "T2",
                         QcReview(user2.id, False, "corrupted"))
                ],
            },
            "STUDY3": {
                Session("STUDY3_ABC_1234_01", "ABC", 1): [
                    Scan("STUDY3_ABC_1234_01_01_DTI60-1000_11", 11,
                         "DTI60-1000", QcReview(user1.id, True))
                ]
            }
        }

        for study in studies:
            add_scans(study, scans[study.id])

        user1.add_studies({
            "STUDY1": ["CMH"],
            "STUDY2": [],
            "STUDY3": []
        })
        user2.add_studies({
            "STUDY1": ["UTO"],
            "STUDY2": ["CMH"]
        })

        return read_only_db
