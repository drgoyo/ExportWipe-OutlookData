"""Safety guards for reviewed VBA; Outlook compilation is a separate Windows host check."""

import re
from pathlib import Path

MACRO_PATH = (
    Path(__file__).resolve().parents[3] / "src/pipelines/vba_extraction/Outlook_RAG_Extractor.bas"
)


def test_macro_structure_and_export_before_cleanup() -> None:
    text = MACRO_PATH.read_text()
    assert len(re.findall(r"^(?:Public|Private) (?:Sub|Function)\b", text, re.M)) == len(
        re.findall(r"^End (?:Sub|Function)$", text, re.M)
    )
    assert '"deletion_mode", "0"' in text
    assert "vbDefaultButton2" in text
    assert "Not cfg.AllowDestructive Or Not cfg.Track2Enabled" in text
    assert "As Integer" not in text
    assert "dim property" not in text.lower()
    commit = text.index('WriteUTF8 technical & "complete.txt", marker')
    assert text.index('WriteUTF8 technical & "metadata.json", metadata') < commit
    assert text.index('mail.SaveAs directory & "Email.msg", Outlook.olMSGUnicode') < commit
    assert text.index("attachment.SaveAsFile") < commit < text.index("If cfg.DeletionMode = 1 Then")
    retry = text.index('fso.DeleteFile technical & "complete.txt", True')
    assert retry < text.index('mail.SaveAs directory & "Email.msg", Outlook.olMSGUnicode')
    assert "Case 0 To 31:" in text
    assert "EscapeJSON(mail.Body)" not in text
    assert 'Format$(mail.ReceivedTime, "yyyy/mm/")' not in text


def test_macro_uses_bounded_sidecars_without_pst_or_global_indexes() -> None:
    text = MACRO_PATH.read_text()
    for removed in (
        "RebuildIndexes",
        "CollectMetadata",
        "Master_Index.jsonl",
        "Master_Context.md",
        "Processed_Cache.log",
        "processedDict",
        "archiveKeys",
        "mail.Copy",
        "AddStoreEx",
    ):
        assert removed not in text
    assert '"archive_pst", False' in text
    assert '"date_filter_mode", "0"' in text
    assert '"process_all_subfolders", True' in text
    assert 'technical = directory & "_rag\\"' in text
    assert '""source_key""' in text
    assert '""outlook_folder""' in text
    assert '"Mail/"' in text
    assert 'directory & "Attachments\\"' in text
    assert text.count("AssertCatalogIdle fso, cfg.OutputDirectory") == 2
    assert "fso.CreateTextFile(lockPath, False, False)" in text
    assert "\\_rag\\catalog.lock" in text
    assert "\\_rag\\catalog_publication.json" in text


def test_macro_recipient_filter_fails_closed_and_resets_each_address() -> None:
    text = MACRO_PATH.read_text()
    private_contacts = text.split("Private Function HasPrivateContact", 1)[1].split(
        "End Function", 1
    )[0]
    assert "HasPrivateContact = True" in private_contacts
    loop = private_contacts.split("For Each recipient In mail.Recipients", 1)[1]
    assert loop.index("address = vbNullString") < loop.index("AddressSMTP(recipient.AddressEntry)")
    assert 'If InStr(1, address, "@", vbBinaryCompare) = 0 Then Exit Function' in loop
    assert "IsFreemail(sender, domains)" in private_contacts
    assert "IsFreemail(address, domains)" in loop
    assert 'domain = blocked Or Right$(domain, Len(blocked) + 1) = "." & blocked' in text
