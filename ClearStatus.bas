Attribute VB_Name = "ClearStatus"
' Optional: clears the Bet Angel status cells (O9, O11) on a sheet when a new market is
' bound to it, so the trigger can fire again. Bet Angel will not place a bet while the
' status cell is filled.
'
' To use: save the workbook as .xlsm, press Alt+F11, File > Import File > ClearStatus.bas,
' then paste the Worksheet_Change handler below into EACH "Bet Angel" sheet's code module.
'
' ---- paste into each Bet Angel sheet module ----
' Private Sub Worksheet_Change(ByVal Target As Range)
'     ClearStatus.OnChange Me, Target
' End Sub
' ------------------------------------------------

Private lastEvent As Object

Public Sub OnChange(ws As Worksheet, Target As Range)
    If lastEvent Is Nothing Then Set lastEvent = CreateObject("Scripting.Dictionary")
    If Intersect(Target, ws.Range("B1")) Is Nothing Then Exit Sub
    Dim ev As String: ev = CStr(ws.Range("B1").Value)
    If lastEvent.Exists(ws.Name) Then
        If lastEvent(ws.Name) <> ev Then
            Application.EnableEvents = False
            ws.Range("O9").ClearContents
            ws.Range("O11").ClearContents
            Application.EnableEvents = True
        End If
    End If
    lastEvent(ws.Name) = ev
End Sub

' Also clears FAILED statuses so a bet can be retried
Public Sub ClearFailed()
    Dim ws As Worksheet, r As Variant
    For Each ws In ThisWorkbook.Worksheets
        If Left(ws.Name, 9) = "Bet Angel" Then
            For Each r In Array(9, 11)
                If InStr(1, CStr(ws.Range("O" & r).Value), "FAILED", vbTextCompare) > 0 Then ws.Range("O" & r).ClearContents
            Next r
        End If
    Next ws
End Sub
