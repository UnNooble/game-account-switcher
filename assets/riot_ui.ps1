# Drives the Riot Client sign-in window through Windows UI Automation (the accessibility interface
# built into Windows): sets the fields, ticks "Stay signed in", presses the arrow. No keystrokes or
# mouse clicks are sent. Reads one base64(UTF-8 JSON) request on stdin, writes one JSON line on stdout.
# The password only ever travels over stdin; it is never written to a file, a log or the command line.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$A  = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
$PC = [System.Windows.Automation.PropertyCondition]

function Emit($o) { [Console]::Out.Write(($o | ConvertTo-Json -Compress -Depth 6)) }

try {
    $raw = [Console]::In.ReadToEnd().Trim()
    $req = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($raw)) | ConvertFrom-Json
} catch {
    Emit @{ ok = $false; error = 'bad request' }; exit 0
}

function Is-RiotProcess($id) {
    try { $n = (Get-Process -Id $id -ErrorAction Stop).ProcessName } catch { return $false }
    # "Riot Client" (the Electron window, name has a space) and older "RiotClientUx"; never the background service.
    return ($n -like 'Riot*Client*') -and ($n -notlike '*Services*') -and ($n -notlike '*Crash*')
}

function Find-RiotWindow {
    $cond = [System.Windows.Automation.PropertyCondition]::new($A::ClassNameProperty, 'Chrome_WidgetWin_1')
    $best = $null; $bestArea = -1
    foreach ($w in $A::RootElement.FindAll($TS::Children, $cond)) {
        try {
            if (-not (Is-RiotProcess $w.Current.ProcessId)) { continue }
            if ($w.Current.IsOffscreen) { continue }
            $r = $w.Current.BoundingRectangle
            $area = if ([double]::IsInfinity($r.Width)) { 0 } else { $r.Width * $r.Height }
            if ($area -gt $bestArea) { $best = $w; $bestArea = $area }
        } catch { continue }
    }
    return $best
}

# What Windows can see, for the log when something doesn't match. Names and kinds only.
function Debug-Windows {
    $out = @{ windows = @(); tree = @{} }
    foreach ($w in $A::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
        try {
            $procName = (Get-Process -Id $w.Current.ProcessId -ErrorAction Stop).ProcessName
            if ($procName -notlike '*Riot*' -and $procName -notlike '*VALORANT*') { continue }
            $r = $w.Current.BoundingRectangle
            $out.windows += @{ proc = $procName; cls = [string]$w.Current.ClassName; title = [string]$w.Current.Name
                               offscreen = [bool]$w.Current.IsOffscreen
                               w = $(if ([double]::IsInfinity($r.Width)) { 0 } else { [int]$r.Width })
                               h = $(if ([double]::IsInfinity($r.Height)) { 0 } else { [int]$r.Height }) }
        } catch { continue }
    }
    $win = Find-RiotWindow
    if ($win) {
        try {
            $kinds = @{}
            foreach ($el in $win.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
                $k = [string]$el.Current.LocalizedControlType
                if ($kinds.ContainsKey($k)) { $kinds[$k]++ } else { $kinds[$k] = 1 }
                if (($kinds.Values | Measure-Object -Sum).Sum -gt 1500) { break }
            }
            $out.tree = $kinds
        } catch { $out.tree = @{ error = [string]$_.Exception.Message } }
    }
    return $out
}

function All($win, $type) {
    $c = [System.Windows.Automation.PropertyCondition]::new($A::ControlTypeProperty, $type)
    return @($win.FindAll($TS::Descendants, $c))
}

function Rect-Top($el)    { try { $t = $el.Current.BoundingRectangle.Top; if ([double]::IsInfinity($t)) { 1e9 } else { $t } } catch { 1e9 } }
function Rect-Left($el)   { try { $l = $el.Current.BoundingRectangle.Left; if ([double]::IsInfinity($l)) { 1e9 } else { $l } } catch { 1e9 } }
function Rect-Bottom($el) { try { $b = $el.Current.BoundingRectangle.Bottom; if ([double]::IsInfinity($b)) { 0 } else { $b } } catch { 0 } }

# A picture of the window: names and kinds only, never typed values.
function Get-Model($win) {
    $edits = @(All $win ($CT::Edit) | ForEach-Object {
        [pscustomobject]@{ el = $_; name = [string]$_.Current.Name; pw = [bool]$_.Current.IsPassword
                           top = (Rect-Top $_); left = (Rect-Left $_); row = [math]::Round((Rect-Top $_) / 12) }
    } | Sort-Object row, left)
    $checks  = @(All $win ($CT::CheckBox))
    $buttons = @(All $win ($CT::Button))
    $links   = @(All $win ($CT::Hyperlink))
    $texts = @(All $win ($CT::Text) | ForEach-Object { ([string]$_.Current.Name).Trim() } |
               Where-Object { $_ -and $_.Length -lt 200 } | Select-Object -Unique -First 60)
    return [pscustomobject]@{ win = $win; edits = $edits; checks = $checks; buttons = $buttons; links = $links; texts = $texts }
}

function Describe($m) {
    return @{
        found   = $true
        edits   = @($m.edits | ForEach-Object { @{ name = $_.name; password = $_.pw } })
        checks  = @($m.checks | ForEach-Object { [string]$_.Current.Name })
        buttons = @($m.buttons | ForEach-Object { @{ name = [string]$_.Current.Name; enabled = [bool]$_.Current.IsEnabled; top = (Rect-Top $_) } })
        links   = @($m.links | ForEach-Object { [string]$_.Current.Name })
        texts   = @($m.texts)
    }
}

# Chromium builds its accessibility tree only after something asks for it, so retry for a while.
function Wait-Model($seconds, $needEdits) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        $win = Find-RiotWindow
        if ($win) {
            $m = Get-Model $win
            if (-not $needEdits -or $m.edits.Count -gt 0) { return $m }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $null
}

function Set-Text($el, $text) {
    try { $el.SetFocus() } catch {}
    $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $vp.SetValue([string]$text)
}

function Press($el) {
    foreach ($pat in @([System.Windows.Automation.InvokePattern]::Pattern,
                       [System.Windows.Automation.SelectionItemPattern]::Pattern)) {
        $obj = $null
        if ($el.TryGetCurrentPattern($pat, [ref]$obj)) {
            if ($obj -is [System.Windows.Automation.InvokePattern]) { $obj.Invoke(); return $true }
            if ($obj -is [System.Windows.Automation.SelectionItemPattern]) { $obj.Select(); return $true }
        }
    }
    return $false
}

function Tick($cb, $want) {
    $obj = $null
    if (-not $cb.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$obj)) { return $false }
    $isOn = ($obj.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On)
    if ($isOn -ne $want) { $obj.Toggle(); Start-Sleep -Milliseconds 200 }
    return ($obj.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) -eq $want
}

# The submit control: a button named like one, else the first enabled button below `$belowY`; never "resend"-type buttons.
$NotSubmit = 'resend|send (it )?again|another|different|didn|cancel|back|help|facebook|google|apple|xbox|playstation|qr'
function Find-Submit($m, $belowY) {
    $enabled = @($m.buttons | Where-Object { $_.Current.IsEnabled })
    foreach ($b in $enabled) {
        $n = [string]$b.Current.Name
        if ($n -match 'sign.?in|submit|verify|confirm|continue|next' -and $n -notmatch $NotSubmit) { return $b }
    }
    $cands = @($enabled | Where-Object { (Rect-Top $_) -ge ($belowY - 2) -and ([string]$_.Current.Name) -notmatch $NotSubmit } |
               Sort-Object { Rect-Top $_ })
    if ($cands.Count -gt 0) { return $cands[0] }
    return $null
}

function Wait-Submit($win, $belowY, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        $m = Get-Model $win
        $s = Find-Submit $m $belowY
        if ($s) { return $s }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    return $null
}

try {
    $wait = [double]($req.wait)
    switch ($req.cmd) {
        'inventory' {
            $m = Wait-Model $wait $false
            if (-not $m) { Emit @{ ok = $true; found = $false }; exit 0 }
            $d = Describe $m; $d.ok = $true; Emit $d
        }
        'fill' {
            $m = Wait-Model $wait $true
            if (-not $m) { Emit @{ ok = $false; found = [bool](Find-RiotWindow); error = 'no sign-in form found'; debug = (Debug-Windows) }; exit 0 }
            $user = $m.edits | Where-Object { -not $_.pw } | Select-Object -First 1
            $pass = $m.edits | Where-Object { $_.pw } | Select-Object -First 1
            if (-not $user -or -not $pass) { $d = Describe $m; $d.ok = $false; $d.error = 'form has no username/password boxes'; $d.debug = (Debug-Windows); Emit $d; exit 0 }
            Set-Text $user.el $req.username
            Set-Text $pass.el $req.password
            $stay = $false
            if ($req.stay) {
                $cb = $m.checks | Where-Object { ([string]$_.Current.Name) -like '*stay*' } | Select-Object -First 1
                if (-not $cb) { $cb = $m.checks | Select-Object -First 1 }
                if ($cb) { $stay = Tick $cb $true }
            }
            $below = if ($m.checks.Count -gt 0) { Rect-Bottom $m.checks[0] } else { Rect-Bottom $pass.el }
            $submit = Wait-Submit $m.win $below 8
            if (-not $submit) { $d = Describe $m; $d.ok = $false; $d.stay = $stay; $d.error = 'the arrow button never became active'; Emit $d; exit 0 }
            $pressed = Press $submit
            Emit @{ ok = $pressed; stay = $stay; submitted = $pressed; error = $(if ($pressed) { '' } else { 'could not press the arrow button' }) }
        }
        'code' {
            $m = Wait-Model $wait $true
            if (-not $m) { Emit @{ ok = $false; error = 'no code box found'; debug = (Debug-Windows) }; exit 0 }
            $boxes = @($m.edits | Where-Object { -not $_.pw })
            if ($boxes.Count -eq 0) { $d = Describe $m; $d.ok = $false; $d.error = 'no code box on this page'; $d.debug = (Debug-Windows); Emit $d; exit 0 }
            $code = [string]$req.code
            $used = @()
            if ($boxes.Count -ge 4 -and $boxes.Count -le 10) {
                # One box per digit (the usual layout): left to right, one character each.
                $n = [math]::Min($code.Length, $boxes.Count)
                for ($i = 0; $i -lt $n; $i++) { Set-Text $boxes[$i].el ([string]$code[$i]); $used += $boxes[$i] }
                $expected = $code.Substring(0, $n)
            } else {
                Set-Text $boxes[0].el $code; $used += $boxes[0]
                $expected = $code
            }
            Start-Sleep -Milliseconds 300
            $got = ''
            foreach ($b in $used) {
                try { $got += [string]$b.el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
            }
            $matched = ($got -replace '\s', '') -eq $expected
            $rem = $m.checks | Where-Object { ([string]$_.Current.Name) -match 'remember|trust|device' } | Select-Object -First 1
            if ($rem) { [void](Tick $rem $true) }
            if (-not $matched) {
                Emit @{ ok = $false; matched = $false; boxes = $boxes.Count; typed = $used.Count; error = 'the code boxes did not hold the digits as typed' }; exit 0
            }
            $below = ($used | ForEach-Object { Rect-Bottom $_.el } | Measure-Object -Maximum).Maximum
            $submit = Wait-Submit $m.win $below 4
            if (-not $submit) { Emit @{ ok = $true; matched = $true; boxes = $boxes.Count; submitted = $false; note = 'no submit button (the page probably submits by itself)' }; exit 0 }
            $pressed = Press $submit
            Emit @{ ok = $pressed; matched = $true; boxes = $boxes.Count; submitted = $pressed }
        }
        'click' {
            $m = Wait-Model $wait $false
            if (-not $m) { Emit @{ ok = $false; error = 'Riot window not found' }; exit 0 }
            $hit = $null
            foreach ($el in @($m.links) + @($m.buttons)) {
                if (([string]$el.Current.Name) -match [string]$req.pattern) { $hit = $el; break }
            }
            if (-not $hit) { Emit @{ ok = $false; error = 'nothing matching on this page' }; exit 0 }
            $pressed = Press $hit
            Emit @{ ok = $pressed; clicked = [string]$hit.Current.Name }
        }
        'debug' { $d = Debug-Windows; $d.ok = $true; Emit $d }
        default { Emit @{ ok = $false; error = 'unknown command' } }
    }
} catch {
    Emit @{ ok = $false; error = ([string]$_.Exception.Message) }
}
