import unittest

from reconcile import RemoteFile, find_existing_upload, is_same_or_renamed


def remote(filename: str, size: int = 100) -> RemoteFile:
    return RemoteFile(filename=filename, size=size, url=f"https://example.com/{filename}")


class IsSameOrRenamedTest(unittest.TestCase):
    def test_matches_exact_and_collision_renames(self):
        for remote_name in ["report.pdf", "report_0.pdf", "report_12.pdf", "REPORT.pdf", "report.PDF"]:
            with self.subTest(remote_name=remote_name):
                self.assertTrue(is_same_or_renamed("report.pdf", remote_name))

    def test_rejects_other_names(self):
        for remote_name in ["", "report_.pdf", "report_a.pdf", "report_0_0.pdf", "report2.pdf",
                            "other.pdf", "xreport.pdf", "report.pdf.exe", "report_٣.pdf"]:
            with self.subTest(remote_name=remote_name):
                self.assertFalse(is_same_or_renamed("report.pdf", remote_name))

    def test_regex_characters_in_local_name_are_literal(self):
        self.assertFalse(is_same_or_renamed("a.b.pdf", "aXb.pdf"))
        self.assertTrue(is_same_or_renamed("a.b.pdf", "a.b_1.pdf"))

    def test_name_without_extension(self):
        self.assertFalse(is_same_or_renamed("report", "report"))


class FindExistingUploadTest(unittest.TestCase):
    def test_no_remote_files(self):
        self.assertIsNone(find_existing_upload("a.pdf", 100, []))

    def test_matches_name_and_size(self):
        match = remote("a_0.pdf", 100)
        self.assertIs(find_existing_upload("a.pdf", 100, [remote("b.pdf"), match]), match)

    def test_size_mismatch_is_not_a_match(self):
        self.assertIsNone(find_existing_upload("a.pdf", 100, [remote("a.pdf", 101), remote("a_0.pdf", 0)]))

    def test_exact_name_has_priority_over_collision_match(self):
        exact = remote("a.pdf")
        renamed = remote("a_0.pdf")
        self.assertIs(find_existing_upload("a.pdf", 100, [renamed, exact]), exact)

    def test_does_not_claim_name_reserved_by_another_local_file(self):
        renamed = remote("a_0.pdf")
        self.assertIsNone(find_existing_upload("a.pdf", 100, [renamed], reserved_names={"a_0.pdf"}))


if __name__ == "__main__":
    unittest.main()
