# Install and run the Outlook RAG extractor

Use **classic Outlook for Windows**. New Outlook, Outlook on the web, Outlook for Mac, and Linux do
not run Outlook VBA. The Python catalog, parsing, database, and dashboard run on Windows, Linux, and
macOS. Export in Outlook first; then transfer the complete export to your Python host if necessary.

## 1. Prepare the output and configuration

1. Start with a small Outlook folder containing copies of representative emails and attachments.
2. Run `uv run outlook-rag-config --config config.yaml` on Windows. Choose a short, absolute, writable
   directory such as `C:\OutlookRAG` or `C:\Users\YourName\Documents\OutlookRAG`. Existing parent
   directories are created as needed. The macro rejects output roots longer than 125 characters and
   shortens descriptive folder names and attachment names to stay within classic Windows path limits.
3. Keep **deletion mode 0 (copy only)**. No PST is created or mounted, and the macro never calls
   `MailItem.Copy` or modifies the source mailbox in this mode. Set `archive_pst=false` when migrating
   an older configuration; `true` is rejected with an explanation rather than silently ignored.
4. Select date mode **0: all**, **1: before the date**, or **2: on/after the date**. Mode 0 is the new
   default. A legacy INI containing only `older_than_date` retains its before/after behavior.
5. Enable recursive subfolders if wanted (`process_all_subfolders=true` by default). Only the selected
   Outlook folder and its descendants are visited; the macro does not automatically scan every store.
6. Keep freemail exclusion enabled unless you intend to include those contacts. The filter checks
   the sender and visible To/CC/BCC recipients against exact domains and their subdomains. Unresolved
   identities are excluded. Distribution-list members and hidden BCC recipients cannot all be inspected;
   the filter is an aid, not a complete privacy classifier.
7. Choose Track 1 for metadata questions, Track 2 for email bodies/attachments and deep RAG, or both.
   Even a Track 1-only export contains full `.msg` backup files, so keep the raw directory private.
8. Save. The GUI writes YAML plus a credential-free `extractor.ini` in the output directory. Record
   its absolute path; LLM tokens and API secrets are never exported to the INI.

The macro does a file-creation and UTF-8 write/delete preflight before reading messages. If Windows
reports “Permission denied,” choose a directory your account can write to and inspect Controlled
Folder Access, OneDrive availability, network-share permissions, or your organization's policy.
Do not run Outlook as administrator or bypass corporate policy as a workaround. Removing PST creation
and source-mail copying avoids the extra mailbox/store write permissions used by the earlier macro;
actual causes still need the reported error and the local Outlook test.

## 2. Enable the Developer tab

1. Select **File → Options → Customize Ribbon** in classic Outlook.
2. Under **Main Tabs**, check **Developer**, then select **OK**.
3. Open **File → Options → Trust Center → Trust Center Settings → Macro Settings**.
4. Prefer signed macros or notification-based approval for reviewed macros. Do not select unrestricted
   “enable all macros.” If policy blocks macros, ask your IT team about approved signing or deployment.
5. Restart Outlook if prompted. Outlook's programmatic-access policy may also prompt when reading
   addresses or message bodies; follow your organization's approved policy rather than disabling it.

## 3. Import, compile, and save

1. Press **Alt+F11**, or select **Developer → Visual Basic**.
2. Select **Project1 (VbaProject.OTM)** in Project Explorer (**Ctrl+R** if hidden).
3. If upgrading, remove the old `Outlook_RAG_Extractor` module after backing it up. Avoid duplicate names.
4. Select **File → Import File** and open
   `src/pipelines/vba_extraction/Outlook_RAG_Extractor.bas`.
5. Select **Debug → Compile Project1**. Outlook supplies its object library; the macro late-binds
   Scripting.FileSystemObject and ADODB.Stream, so no additional reference or 32/64-bit declaration
   is required. The `Attribute VB_Name` line belongs to the imported `.bas` file, not an editor paste.
6. Press **Ctrl+S**. If your organization requires signing, use **Tools → Digital Signature** and
   the approved certificate. Re-sign after modifying the macro.

## 4. Export and browse the result

1. Select the source Outlook folder. Press **Alt+F8**, choose **ExtractOutlookForRAG**, and select **Run**.
2. Paste the generated INI path into the prompt. Canceling stops without accessing messages.
3. Wait for the exported/skipped/failed summary. The macro continues after individual item or folder
   failures; inspect the VBA **Immediate** window (**Ctrl+G**) for the error descriptions.
4. Open several `.msg` files and attachments to check the copy-only export before exporting a large
   folder. Do not run the Python catalog or ingestion while `export.lock` exists.

Each mail keeps its contents together:

```text
OutlookRAG/
  extractor.ini
  Mail/
    2026/
      10/
        2026-10-13_09-30_Project proposal_sender@example.com_6F27AB10/
          Email.msg                    # Full Unicode Outlook backup
          Email.txt                    # Track 2 only, UTF-8 body
          Attachments/                 # Track 2 only, qualifying by-value files
            001 Proposal.docx
            002 Budget.xlsx
          _rag/
            metadata.json              # Metadata and relative paths, never body contents
            source_id.txt              # Full StoreID:EntryID identity
            complete.txt               # Last-written export checkpoint
  _rag/                                # Python-owned catalog state
    catalog.duckdb
  Master_Index.jsonl                    # Generated by Python, metadata/path references
  Master_Context.md                     # Generated by Python, metadata only
```

Folder names use date, a shortened readable subject and sender, and a stable suffix. Attachment
ordinals prevent duplicate names from overwriting each other. The original Outlook folder is retained
in `outlook_folder` metadata, while the human-facing tree groups each email with its attachments.
Names are sanitized for Windows/SharePoint characters; date/month separators and ISO timestamps
are independent of Windows locale. Message timestamps retain Outlook's local wall time, without an
invented timezone; use a consistent timezone when combining exports from different computers.

For OneDrive or SharePoint, export first to a local directory, finish the Python catalog, then sync
or upload the resulting snapshot. Keep `.msg`, `Email.txt`, `Attachments`, and `_rag` together so the
relative paths continue to resolve. The exact SharePoint URL length, tenant file policy, quotas,
and OneDrive sync limits still apply; the macro cannot validate those remotely. Catalog DuckDB state
is local mutable state: run one catalog process on a local working copy, then sync after it closes.
A short local path avoids Outlook/Windows path errors even when the eventual document URL is long.

## 5. Generate scalable indexes in Python

The macro writes only one bounded sidecar per message. It does **not** append JSONL, build Markdown,
read a mailbox-sized checkpoint log, or keep all message identities in memory.

After the export lock is gone, from the repository directory run:

```bash
uv run outlook-rag --config config.yaml catalog
uv run outlook-rag --config config.yaml ingest --manifest data/raw/Master_Index.jsonl
```

Adjust the manifest path to the configured extraction directory. Python discovers completed
sidecars, validates paths, and batches metadata through Polars into a disk-backed DuckDB catalog.
It streams `Master_Index.jsonl` and `Master_Context.md` rather than accumulating the entire mailbox
in memory. Track 1 receives metadata only; ingestion reads the separate Track 2 files.

The macro refuses to start while `_rag/catalog.lock` or an unfinished
`_rag/catalog_publication.json` exists. Finish/recover the Python catalog before exporting again.
Do not manually delete an active lock. After a crash, first confirm that its owning process has
stopped, then follow the Python catalog's recovery instructions.

## 6. Reruns and optional mailbox cleanup

Completion markers retain the full source identity and extraction signature. A matching completed
message is skipped without a global in-memory cache. If tracks or size thresholds change, the old
marker is removed before rewriting artifacts; interrupted attempts do not look complete. A shortened
identity collision is checked against the full StoreID/EntryID before overwriting an existing folder.

Changing a subject/sender, moving a mail so that Outlook assigns a new EntryID, or changing the
output root can create a new folder. The Python catalog deduplicates identical email IDs and rejects
conflicting source identities. No export process can infer that distinct Outlook EntryIDs represent
one logical message. Changing privacy rules does not remove data previously exported; use a fresh
output directory for a different retention/privacy policy. A checkpoint is not a backup integrity
checker: if exported files were manually removed, remove that mail's completed marker and reexport
from the still-available source or restore a backup.

Mode **1** deletes only successfully exported by-value attachments. Mode **2** deletes the entire
processed mail (Outlook's normal delete behavior). Both require Track 2, `allow_destructive=true`,
and an interactive **Yes** with **No** as default. A complete Unicode `.msg`, all selected files,
metadata, and the completion marker are saved before any source modification. Maintain and verify
an independent mailbox backup before using either mode. Large mailboxes are not a reason to enable
cleanup: mode 0 remains recommended.

An export failure leaves that message untouched by the cleanup stage. If cleanup itself fails after
export, the backup remains, a failure is reported, and the checkpoint prevents automatic retry of
the destructive operation; inspect and resolve that cleanup manually. Outlook and filesystem writes
are not a distributed transaction. If a crash left `export.lock`, remove only that lock after ensuring
no Outlook export is running; already completed messages are skipped on rerun.

## Verification limits

Repository tests check macro structure, privacy-routing source guards, safe defaults, bounded state,
locale-independent paths, lock cooperation, and export-before-cleanup ordering. This Linux host has
no Outlook COM/VBA compiler, so no runtime mailbox or destructive operation was executed. Perform
**Debug → Compile Project1** and a small copy-only test in classic Outlook before production use.
