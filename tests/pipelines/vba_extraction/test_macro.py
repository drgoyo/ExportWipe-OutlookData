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
    assert "If Not cfg.AllowDestructive Then" in text
    assert "As Integer" not in text
    assert "dim property" not in text.lower()
    commit = text.index('WriteUTF8 stateDirectory & "complete.txt", marker')
    assert text.index('mail.SaveAs directory & "Email.msg", Outlook.olMSGUnicode') < commit
    assert text.index("attachment.SaveAsFile") < commit < text.index("If cfg.DeletionMode = 1 Then")
    assert text.index("cacheStream.WriteLine sourceKey & vbTab & signature") < commit
    retry = text.index('fso.DeleteFile stateDirectory & "complete.txt", True')
    assert retry < text.index('mail.SaveAs directory & "Email.msg", Outlook.olMSGUnicode')
    assert 'Format$(mail.ReceivedTime, "yyyy/mm/")' not in text


def test_macro_outputs_only_physical_files_and_internal_state() -> None:
    text = MACRO_PATH.read_text()
    for removed in (
        "RebuildIndexes",
        "CollectMetadata",
        "Master_Index.jsonl",
        "Master_Context.md",
        "Email.txt",
        "metadata.json",
        "mail.Body",
        "HTMLBody",
        "RTFBody",
        "EscapeJSON",
        "JSONString",
        "relativeDirectory",
        "Track1Enabled",
        "Track2Enabled",
        "processedDict",
        "archiveKeys",
        "mail.Copy",
        "AddStoreEx",
    ):
        assert removed not in text
    assert '"archive_pst", False' in text
    assert '"date_filter_mode", "0"' in text
    assert '"process_all_subfolders", True' in text
    assert 'stateDirectory = directory & "_state\\"' in text
    assert 'signature = "raw-msg-v1:"' in text
    assert '"\\Mail\\"' in text
    assert '"\\Processed_Cache.log", 8, True, -1' in text
    assert "cacheStream.Read" not in text
    writes = re.findall(r"^\s+WriteUTF8 (.+)$", text, re.M)
    assert writes == [
        'stateDirectory & "source_id.txt", sourceKey',
        'stateDirectory & "complete.txt", marker',
    ]
    assert text.count("AssertCatalogIdle fso, cfg.OutputDirectory") == 2
    assert "fso.CreateTextFile(lockPath, False, False)" in text
    assert "\\_rag\\catalog.lock" in text
    assert "\\_rag\\catalog_publication.json" in text


def test_type_folders_and_idempotency_do_not_depend_on_rag_artifacts() -> None:
    text = MACRO_PATH.read_text()
    exporting = text.split("Private Function ExportOneMail", 1)[1].split("End Function", 1)[0]
    assert 'If ReadUTF8(stateDirectory & "source_id.txt") <> sourceKey Then' in exporting
    assert 'fso.FileExists(stateDirectory & "complete.txt")' in exporting
    assert 'fso.FileExists(directory & "Email.msg")' in exporting
    assert 'If ReadUTF8(stateDirectory & "complete.txt") = marker Then Exit Function' in exporting
    assert "AttachmentTypeFolder(fso, attachment.FileName)" in exporting
    assert "240 - Len(typeDirectory) - Len(filename)" in exporting
    assert "For i = 1 To mail.Attachments.Count" in exporting
    types = text.split("Private Function AttachmentTypeFolder", 1)[1].split("End Function", 1)[0]
    assert "LCase$(fso.GetExtensionName(filename))" in types
    assert "Len(extension) = 0 Or Len(extension) > 12" in types
    assert 'Like "[a-z0-9]"' in types
    assert 'AttachmentTypeFolder = "Other"' in types
    assert 'AttachmentTypeFolder = "Type_" & extension' in types


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
