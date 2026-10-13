Attribute VB_Name = "Outlook_RAG_Extractor"
Option Explicit

' Classic Outlook for Windows. Export physical files and operational state only.
' Python Phase 2 owns MSG parsing, text extraction, metadata and all RAG modeling.
Private Type ExportConfiguration
    OutputDirectory As String
    FilterDate As Date
    DateFilterMode As Long
    MinimumAttachmentBytes As Long
    ExcludeFreemail As Boolean
    FreemailDomains As String
    ProcessAllSubfolders As Boolean
    DeletionMode As Long
    AllowDestructive As Boolean
End Type

Public Sub ExtractOutlookForRAG()
    Dim cfg As ExportConfiguration, iniPath As String, lockPath As String, errorText As String
    Dim fso As Object, lockStream As Object, cacheStream As Object, source As Outlook.MAPIFolder
    Dim exported As Long, skipped As Long, failed As Long, acquiredLock As Boolean
    On Error GoTo FatalError
    iniPath = InputBox("Path to the extractor.ini saved by the Python configuration GUI:", _
        "Outlook RAG", Environ$("USERPROFILE") & "\Documents\OutlookRAG\extractor.ini")
    If Len(Trim$(iniPath)) = 0 Then Exit Sub
    cfg = LoadConfiguration(Trim$(iniPath))
    If cfg.DeletionMode < 0 Or cfg.DeletionMode > 2 Then
        Err.Raise vbObjectError + 102, , "deletion_mode must be 0, 1, or 2."
    End If
    If cfg.DeletionMode <> 0 Then
        If Not cfg.AllowDestructive Then
            Err.Raise vbObjectError + 103, , "Cleanup requires allow_destructive=true."
        End If
        If MsgBox("Cleanup mode " & cfg.DeletionMode & " modifies the source mailbox." & vbCrLf & _
            "A complete .msg is saved first. Confirm an independent mailbox backup exists." & _
            vbCrLf & "Continue?", vbYesNo + vbExclamation + vbDefaultButton2, _
            "Confirm destructive cleanup") <> vbYes Then Exit Sub
    End If
    If Application.ActiveExplorer Is Nothing Then
        Err.Raise vbObjectError + 104, , "Open Outlook and select the source folder."
    End If
    Set source = Application.ActiveExplorer.CurrentFolder
    Set fso = CreateObject("Scripting.FileSystemObject")
    EnsureDirectory fso, cfg.OutputDirectory
    AssertCatalogIdle fso, cfg.OutputDirectory
    ' CreateTextFile overwrite=False atomically refuses an existing export lock.
    lockPath = cfg.OutputDirectory & "\export.lock"
    Set lockStream = fso.CreateTextFile(lockPath, False, False)
    acquiredLock = True
    lockStream.WriteLine "Outlook export started " & Format$(Now, "yyyy-mm-dd hh:nn:ss")
    lockStream.Close
    AssertCatalogIdle fso, cfg.OutputDirectory
    ' Append operational history; never load a mailbox-sized log or identity cache.
    Set cacheStream = fso.OpenTextFile(cfg.OutputDirectory & "\Processed_Cache.log", 8, True, -1)
    ProcessFolder source, cfg, fso, cacheStream, exported, skipped, failed
    cacheStream.Close
    fso.DeleteFile lockPath, True
    acquiredLock = False
    MsgBox "Export complete." & vbCrLf & "Exported: " & exported & "; skipped: " & skipped & _
        "; failed: " & failed & vbCrLf & "Output: " & cfg.OutputDirectory & vbCrLf & _
        "Files are ready for Python Phase 2 MSG parsing. Errors: Ctrl+G in the VBA editor.", _
        vbInformation, "Outlook RAG"
    Exit Sub
FatalError:
    errorText = Err.Description
    On Error Resume Next
    If Not cacheStream Is Nothing Then cacheStream.Close
    If Not lockStream Is Nothing Then lockStream.Close
    If acquiredLock Then fso.DeleteFile lockPath, True
    On Error GoTo 0
    MsgBox "Export stopped: " & errorText & vbCrLf & _
        "Use a writable local folder and copy-only mode. Check Ctrl+G for item failures.", _
        vbCritical, "Outlook RAG"
End Sub

Private Sub ProcessFolder(ByVal folder As Outlook.MAPIFolder, ByRef cfg As ExportConfiguration, _
    ByVal fso As Object, ByVal cacheStream As Object, ByRef exported As Long, _
    ByRef skipped As Long, ByRef failed As Long)
    Dim items As Outlook.Items, item As Object, child As Outlook.MAPIFolder
    Dim i As Long, errorText As String, visitingChildren As Boolean
    On Error GoTo FolderError
    Set items = folder.Items
    For i = items.Count To 1 Step -1
        errorText = vbNullString
        Set item = ReadItem(items, i, errorText)
        If Len(errorText) > 0 Then
            failed = failed + 1
            Debug.Print "Cannot read item in " & FolderName(folder) & ": " & errorText
        ElseIf Not item Is Nothing Then
            If TypeOf item Is Outlook.MailItem Then
                Select Case ExportOneMail(item, folder, cfg, fso, cacheStream, errorText)
                    Case 1: exported = exported + 1
                    Case 0: skipped = skipped + 1
                    Case -1
                        failed = failed + 1
                        Debug.Print "Export failed in " & FolderName(folder) & ": " & errorText
                End Select
            End If
        End If
    Next i
VisitChildren:
    visitingChildren = True
    If cfg.ProcessAllSubfolders Then
        For Each child In folder.Folders
            ProcessFolder child, cfg, fso, cacheStream, exported, skipped, failed
        Next child
    End If
    Exit Sub
FolderError:
    failed = failed + 1
    Debug.Print "Folder access failed in " & FolderName(folder) & ": " & Err.Description
    If visitingChildren Then Exit Sub
    Resume VisitChildren
End Sub

Private Function ReadItem(ByVal items As Outlook.Items, ByVal position As Long, _
    ByRef errorText As String) As Object
    On Error GoTo ReadError
    Set ReadItem = items.Item(position)
    Exit Function
ReadError:
    errorText = Err.Description
End Function

' Returns 1 when exported, 0 when filtered/checkpointed, -1 on an item failure.
Private Function ExportOneMail(ByVal mail As Outlook.MailItem, ByVal folder As Outlook.MAPIFolder, _
    ByRef cfg As ExportConfiguration, ByVal fso As Object, ByVal cacheStream As Object, _
    ByRef errorText As String) As Long
    Dim sender As String, sourceKey As String, signature As String, suffix As String
    Dim directory As String, stateDirectory As String, marker As String, legacyIdentity As String
    Dim attachment As Outlook.Attachment, filename As String, typeDirectory As String
    Dim i As Long, extracted As Object, folderBudget As Long
    On Error GoTo ItemError
    sender = SenderSMTP(mail)
    If cfg.ExcludeFreemail Then
        If HasPrivateContact(mail, sender, cfg.FreemailDomains) Then Exit Function
    End If
    Select Case cfg.DateFilterMode
        Case 1: If DateValue(mail.ReceivedTime) >= cfg.FilterDate Then Exit Function
        Case 2: If DateValue(mail.ReceivedTime) < cfg.FilterDate Then Exit Function
    End Select
    sourceKey = folder.StoreID & ":" & mail.EntryID
    If Len(mail.EntryID) = 0 Then Err.Raise vbObjectError + 105, , "Message has no stable EntryID."
    suffix = CRC32Hex(sourceKey)
    folderBudget = 180 - Len(cfg.OutputDirectory) - 14
    directory = cfg.OutputDirectory & "\Mail\" & Format$(mail.ReceivedTime, "yyyy") & "\" & _
        Format$(mail.ReceivedTime, "mm") & "\" & _
        FriendlyFolder(mail, sender, suffix, folderBudget) & "\"
    stateDirectory = directory & "_state\"
    EnsureDirectory fso, stateDirectory
    If fso.FileExists(stateDirectory & "source_id.txt") Then
        If ReadUTF8(stateDirectory & "source_id.txt") <> sourceKey Then
            Err.Raise vbObjectError + 106, , "Identity collision; use a different export root."
        End If
    End If
    ' Read old operational identity only to prevent overwriting a different archived message.
    legacyIdentity = directory & "_rag\source_id.txt"
    If fso.FileExists(legacyIdentity) Then
        If ReadUTF8(legacyIdentity) <> sourceKey Then
            Err.Raise vbObjectError + 106, , "Legacy identity collision; use a fresh export root."
        End If
    End If
    signature = "raw-msg-v1:" & CStr(cfg.MinimumAttachmentBytes)
    marker = sourceKey & vbLf & signature
    If fso.FileExists(stateDirectory & "complete.txt") And _
        fso.FileExists(stateDirectory & "source_id.txt") And fso.FileExists(directory & "Email.msg") Then
        If ReadUTF8(stateDirectory & "complete.txt") = marker Then Exit Function
    End If
    ' Invalidate an older checkpoint before overwriting any artifacts on a changed configuration.
    If fso.FileExists(stateDirectory & "complete.txt") Then fso.DeleteFile stateDirectory & "complete.txt", True
    WriteUTF8 stateDirectory & "source_id.txt", sourceKey
    mail.SaveAs directory & "Email.msg", Outlook.olMSGUnicode
    Set extracted = CreateObject("Scripting.Dictionary") ' One message only; no mailbox-sized cache.
    For i = 1 To mail.Attachments.Count
        Set attachment = mail.Attachments.Item(i)
        If attachment.Type = Outlook.olByValue And attachment.Size >= cfg.MinimumAttachmentBytes Then
            typeDirectory = directory & "Attachments\" & AttachmentTypeFolder(fso, attachment.FileName) & "\"
            EnsureDirectory fso, typeDirectory
            filename = Format$(i, "000") & " "
            filename = filename & SafeName(attachment.FileName, 240 - Len(typeDirectory) - Len(filename), True)
            attachment.SaveAsFile typeDirectory & filename
            extracted.Add CStr(i), True
        End If
    Next i
    ' Operational history may repeat after an interrupted run; the per-mail marker is authoritative.
    cacheStream.WriteLine sourceKey & vbTab & signature
    ' Every physical artifact and checkpoint is committed before any mailbox modification.
    WriteUTF8 stateDirectory & "complete.txt", marker
    If cfg.DeletionMode = 1 Then
        For i = mail.Attachments.Count To 1 Step -1
            If extracted.Exists(CStr(i)) Then mail.Attachments.Item(i).Delete
        Next i
        If extracted.Count > 0 Then mail.Save
    ElseIf cfg.DeletionMode = 2 Then
        mail.Delete
    End If
    ExportOneMail = 1
    Exit Function
ItemError:
    errorText = Err.Description
    ExportOneMail = -1
End Function

Private Function LoadConfiguration(ByVal path As String) As ExportConfiguration
    Dim cfg As ExportConfiguration, values As Object, lines As Variant, line As Variant
    Dim position As Long, key As String, value As String, dateText As String, dateParts As Variant
    Set values = CreateObject("Scripting.Dictionary")
    lines = Split(Replace(ReadUTF8(path), vbCr, vbNullString), vbLf)
    For Each line In lines
        value = Trim$(CStr(line))
        If Len(value) > 0 And Left$(value, 1) <> "#" And Left$(value, 1) <> ";" Then
            position = InStr(1, value, "=", vbBinaryCompare)
            If position < 2 Then Err.Raise vbObjectError + 107, , "Invalid INI line."
            key = LCase$(Trim$(Left$(value, position - 1)))
            values(key) = Trim$(Mid$(value, position + 1))
        End If
    Next line
    cfg.OutputDirectory = ValueOrDefault(values, "output_directory", _
        Environ$("USERPROFILE") & "\Documents\OutlookRAG")
    If Right$(cfg.OutputDirectory, 1) = "\" Then
        cfg.OutputDirectory = Left$(cfg.OutputDirectory, Len(cfg.OutputDirectory) - 1)
    End If
    If Not ((Len(cfg.OutputDirectory) > 2 And Mid$(cfg.OutputDirectory, 2, 2) = ":\") _
        Or Left$(cfg.OutputDirectory, 2) = "\\") Then
        Err.Raise vbObjectError + 108, , "Use an absolute Windows output directory."
    End If
    If Len(cfg.OutputDirectory) > 125 Then
        Err.Raise vbObjectError + 109, , "Choose an output directory shorter than 126 characters."
    End If
    dateText = ValueOrDefault(values, "filter_date", "2026-01-01")
    dateParts = Split(dateText, "-")
    If UBound(dateParts) <> 2 Then Err.Raise vbObjectError + 110, , "Use filter_date=YYYY-MM-DD."
    cfg.FilterDate = DateSerial(CLng(dateParts(0)), CLng(dateParts(1)), CLng(dateParts(2)))
    If Format$(cfg.FilterDate, "yyyy-mm-dd") <> dateText Then
        Err.Raise vbObjectError + 111, , "Invalid calendar date."
    End If
    cfg.DateFilterMode = CLng(ValueOrDefault(values, "date_filter_mode", "0"))
    If Not values.Exists("date_filter_mode") And values.Exists("older_than_date") Then
        If BooleanValue(values, "older_than_date", True) Then
            cfg.DateFilterMode = 1
        Else
            cfg.DateFilterMode = 2
        End If
    End If
    If cfg.DateFilterMode < 0 Or cfg.DateFilterMode > 2 Then
        Err.Raise vbObjectError + 112, , "date_filter_mode must be 0 (all), 1 (before), or 2 (from)."
    End If
    cfg.MinimumAttachmentBytes = CLng(ValueOrDefault(values, "minimum_attachment_bytes", "0"))
    If cfg.MinimumAttachmentBytes < 0 Then Err.Raise vbObjectError + 113, , "Negative attachment threshold."
    cfg.ExcludeFreemail = BooleanValue(values, "exclude_freemail", True)
    cfg.FreemailDomains = ValueOrDefault(values, "freemail_domains", _
        "gmail.com,googlemail.com,outlook.com,hotmail.com,live.com,web.de,gmx.de,gmx.net,gmx.com," & _
        "yahoo.com,yahoo.de,icloud.com,me.com,mac.com,t-online.de,freenet.de,aol.com")
    cfg.ProcessAllSubfolders = BooleanValue(values, "process_all_subfolders", True)
    If BooleanValue(values, "archive_pst", False) Then
        Err.Raise vbObjectError + 114, , "Set archive_pst=false; this extractor saves independent MSG backups."
    End If
    cfg.DeletionMode = CLng(ValueOrDefault(values, "deletion_mode", "0"))
    cfg.AllowDestructive = BooleanValue(values, "allow_destructive", False)
    LoadConfiguration = cfg
End Function

Private Function ValueOrDefault(ByVal values As Object, ByVal key As String, ByVal fallback As String) As String
    If values.Exists(key) Then ValueOrDefault = values(key) Else ValueOrDefault = fallback
End Function

Private Function BooleanValue(ByVal values As Object, ByVal key As String, ByVal fallback As Boolean) As Boolean
    Dim value As String
    BooleanValue = fallback
    If Not values.Exists(key) Then Exit Function
    value = LCase$(Trim$(values(key)))
    If value = "true" Or value = "1" Then
        BooleanValue = True
    ElseIf value = "false" Or value = "0" Then
        BooleanValue = False
    Else
        Err.Raise vbObjectError + 115, , "Invalid Boolean for " & key
    End If
End Function

' Unknown sender/recipient identities fail closed; includes To, CC, and BCC recipients.
Private Function HasPrivateContact(ByVal mail As Outlook.MailItem, ByVal sender As String, _
    ByVal domains As String) As Boolean
    Dim recipient As Outlook.Recipient, address As String
    HasPrivateContact = True
    If InStr(1, sender, "@", vbBinaryCompare) = 0 Then Exit Function
    If IsFreemail(sender, domains) Then Exit Function
    For Each recipient In mail.Recipients
        address = vbNullString
        On Error Resume Next
        address = AddressSMTP(recipient.AddressEntry)
        If InStr(1, address, "@", vbBinaryCompare) = 0 Then address = recipient.Address
        On Error GoTo 0
        If InStr(1, address, "@", vbBinaryCompare) = 0 Then Exit Function
        If IsFreemail(address, domains) Then Exit Function
    Next recipient
    HasPrivateContact = False
End Function

Private Function SenderSMTP(ByVal mail As Outlook.MailItem) As String
    On Error Resume Next
    SenderSMTP = AddressSMTP(mail.Sender)
    If InStr(1, SenderSMTP, "@", vbBinaryCompare) = 0 Then SenderSMTP = mail.SenderEmailAddress
    On Error GoTo 0
    SenderSMTP = LCase$(Trim$(SenderSMTP))
End Function

Private Function AddressSMTP(ByVal address As Outlook.AddressEntry) As String
    Dim user As Outlook.ExchangeUser, distribution As Outlook.ExchangeDistributionList
    On Error Resume Next
    If address Is Nothing Then Exit Function
    If address.Type = "EX" Then
        Set user = address.GetExchangeUser
        If Not user Is Nothing Then AddressSMTP = user.PrimarySmtpAddress
        If Len(AddressSMTP) = 0 Then
            Set distribution = address.GetExchangeDistributionList
            If Not distribution Is Nothing Then AddressSMTP = distribution.PrimarySmtpAddress
        End If
        If Len(AddressSMTP) = 0 Then
            AddressSMTP = address.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x39FE001E")
        End If
    Else
        AddressSMTP = address.Address
    End If
    On Error GoTo 0
    AddressSMTP = LCase$(Trim$(AddressSMTP))
End Function

Private Function IsFreemail(ByVal email As String, ByVal domains As String) As Boolean
    Dim domain As String, item As Variant, blocked As String, position As Long
    position = InStrRev(email, "@")
    If position = 0 Then Exit Function
    domain = LCase$(Trim$(Mid$(email, position + 1)))
    For Each item In Split(domains, ",")
        blocked = LCase$(Trim$(CStr(item)))
        If Len(blocked) > 0 Then
            If domain = blocked Or Right$(domain, Len(blocked) + 1) = "." & blocked Then
                IsFreemail = True
                Exit Function
            End If
        End If
    Next item
End Function

Private Function FolderName(ByVal folder As Outlook.MAPIFolder) As String
    On Error Resume Next
    FolderName = folder.FolderPath
    On Error GoTo 0
End Function

Private Sub EnsureDirectory(ByVal fso As Object, ByVal path As String)
    Dim parent As String
    If fso.FolderExists(path) Then Exit Sub
    parent = fso.GetParentFolderName(path)
    If Len(parent) = 0 Then Err.Raise vbObjectError + 116, , "Cannot create output directory: " & path
    If Not fso.FolderExists(parent) Then EnsureDirectory fso, parent
    fso.CreateFolder path
End Sub

Private Sub AssertCatalogIdle(ByVal fso As Object, ByVal root As String)
    If fso.FileExists(root & "\_rag\catalog.lock") Or _
        fso.FileExists(root & "\_rag\catalog_publication.json") Then
        Err.Raise vbObjectError + 118, , "Python catalog is active or requires recovery; finish it before exporting."
    End If
End Sub

Private Function FriendlyFolder(ByVal mail As Outlook.MailItem, ByVal sender As String, _
    ByVal suffix As String, ByVal budget As Long) As String
    Dim description As String
    description = SafeName(mail.Subject, 32, False) & "_" & SafeName(sender, 20, False)
    FriendlyFolder = Format$(mail.ReceivedTime, "yyyy-mm-dd_hh-nn") & "_" & _
        SafeLeft(description, budget - 26) & "_" & suffix
End Function

' Ordinal/date prefixes avoid Windows device names; preserve attachment extensions when shortening.
Private Function SafeName(ByVal value As String, ByVal limit As Long, ByVal preserveExtension As Boolean) As String
    Dim result As String, character As String, code As Long, i As Long, extension As String
    For i = 1 To Len(value)
        character = Mid$(value, i, 1)
        code = AscW(character) And &HFFFF&
        If code < 32 Or InStr(1, "\/:*?""<>|#%", character, vbBinaryCompare) > 0 Then character = "_"
        result = result & character
    Next i
    result = Replace(result, "_vti_", "_vti-", 1, -1, vbTextCompare)
    Do While Len(result) > 0
        If Right$(result, 1) <> "." And Right$(result, 1) <> " " Then Exit Do
        result = Left$(result, Len(result) - 1)
    Loop
    If Len(result) = 0 Then result = "No subject"
    If limit > 100 Then limit = 100
    If limit < 12 Then Err.Raise vbObjectError + 117, , "Export path is too long; choose a shorter output directory."
    If Len(result) > limit Then
        i = InStrRev(result, ".")
        If preserveExtension And i > 0 And Len(result) - i < 12 Then extension = Mid$(result, i)
        result = SafeLeft(result, limit - Len(extension)) & extension
    End If
    Do While Len(result) > 0
        If Right$(result, 1) <> "." And Right$(result, 1) <> " " Then Exit Do
        result = Left$(result, Len(result) - 1)
    Loop
    SafeName = result
End Function

' Avoid splitting an emoji/supplementary Unicode character at a UTF-16 truncation boundary.
Private Function SafeLeft(ByVal value As String, ByVal length As Long) As String
    Dim code As Long
    SafeLeft = Left$(value, length)
    If Len(SafeLeft) = 0 Then Exit Function
    code = AscW(Right$(SafeLeft, 1)) And &HFFFF&
    If code >= &HD800& And code <= &HDBFF& Then SafeLeft = Left$(SafeLeft, Len(SafeLeft) - 1)
End Function

Private Function AttachmentTypeFolder(ByVal fso As Object, ByVal filename As String) As String
    Dim extension As String, character As String, i As Long
    AttachmentTypeFolder = "Other"
    extension = LCase$(fso.GetExtensionName(filename))
    If Len(extension) = 0 Or Len(extension) > 12 Then Exit Function
    For i = 1 To Len(extension)
        character = Mid$(extension, i, 1)
        If Not character Like "[a-z0-9]" Then Exit Function
    Next i
    ' A fixed prefix prevents Windows device names such as CON, AUX and COM1.
    AttachmentTypeFolder = "Type_" & extension
End Function

' Full source identity is checked on disk, so a CRC collision cannot overwrite another email.
Private Function CRC32Hex(ByVal value As String) As String
    Dim crc As Long, i As Long, bit As Long
    crc = &HFFFFFFFF
    For i = 1 To Len(value)
        crc = crc Xor (AscW(Mid$(value, i, 1)) And &HFF&)
        For bit = 1 To 8
            If (crc And 1) <> 0 Then
                crc = UnsignedShiftRight(crc) Xor &HEDB88320
            Else
                crc = UnsignedShiftRight(crc)
            End If
        Next bit
    Next i
    CRC32Hex = Right$("00000000" & Hex$(Not crc), 8)
End Function

Private Function UnsignedShiftRight(ByVal value As Long) As Long
    UnsignedShiftRight = (value And &H7FFFFFFF) \ 2
    If value < 0 Then UnsignedShiftRight = UnsignedShiftRight Or &H40000000
End Function

Private Sub WriteUTF8(ByVal path As String, ByVal value As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2: stream.Charset = "utf-8": stream.Open
    stream.WriteText value
    stream.SaveToFile path, 2
    stream.Close
End Sub

Private Function ReadUTF8(ByVal path As String) As String
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2: stream.Charset = "utf-8": stream.Open
    stream.LoadFromFile path
    ReadUTF8 = stream.ReadText
    stream.Close
End Function
