-- Stem2AAF installer
--
-- How to use: double-click this file (it opens in Script Editor, which
-- comes with every Mac - nothing to install). Then click the Run button
-- (the triangle/play icon) in Script Editor's toolbar. No Terminal window
-- will appear; progress happens invisibly, and you'll get a dialog when
-- it's done or if something went wrong.
--
-- Whatever happens, the full build log is always saved to
-- ~/Desktop/Stem2AAF_build_log.txt so you never have to scroll through
-- or screenshot a dialog to read it - just open that file, or attach it
-- if you need to share the output with someone.

set scriptPath to POSIX path of (path to me)
set projectFolder to do shell script "dirname " & quoted form of scriptPath
set logPath to (POSIX path of (path to desktop)) & "Stem2AAF_build_log.txt"

-- `do shell script` hands back its output with carriage returns as the
-- line separator, so writing it out verbatim produced a 750 KB file that
-- is a single line as far as most editors are concerned - awkward for
-- something the dialogs tell you to just open and read. This swaps them
-- for linefeeds first.
on crToLf(theText)
	set savedDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to return
	set theParts to every text item of theText
	set AppleScript's text item delimiters to linefeed
	set theResult to theParts as text
	set AppleScript's text item delimiters to savedDelimiters
	return theResult
end crToLf

on writeLog(contents, logPath)
	try
		set fileRef to open for access POSIX file logPath with write permission
		set eof of fileRef to 0
		write my crToLf(contents) to fileRef as Çclass utf8È
		close access fileRef
	on error
		try
			close access POSIX file logPath
		end try
	end try
end writeLog

display dialog "This will build Stem2AAF.app and install it to your Applications folder. This can take a few minutes - click OK to start." buttons {"Cancel", "OK"} default button "OK"

try
	set shellCommand to "cd " & quoted form of projectFolder & " && /bin/bash build.sh 2>&1"
	-- Without this, macOS's own Apple Event Manager silently gives up on
	-- do shell script after its default timeout (about 2 minutes) and
	-- reports a generic "AppleEvent timed out" error - even though the
	-- actual build might have gone on to succeed in the background. A
	-- full build (creating a venv, installing dependencies, running
	-- py2app twice) can genuinely take longer than that on a slower Mac
	-- or a cold pip cache, so this widens the ceiling well past anything
	-- a real build should ever need.
	with timeout of 1800 seconds
		set buildOutput to do shell script shellCommand
	end timeout
	my writeLog(buildOutput, logPath)
	
	if buildOutput contains "BUILD_COMPLETE_OK" then
		display dialog "Stem2AAF is installed in your Applications folder. To remove it later, use \"Uninstall Stem2AAF...\" from its menu bar icon." & return & return & "First time you open it: right-click it in Applications, choose Open, then click Open again - this is only needed once, since it isn't signed with an Apple Developer certificate." & return & return & "Full build log saved to ~/Desktop/Stem2AAF_build_log.txt" buttons {"OK"} default button "OK"
	else
		display dialog "The build finished but something looks off. Full details were saved to:" & return & return & logPath & return & return & "Open that file (or send it over) to see exactly what happened." buttons {"OK"} default button "OK"
	end if
	
on error errMsg
	my writeLog(errMsg, logPath)
	display dialog "The build failed. Full details were saved to:" & return & return & logPath & return & return & "Open that file (or send it over) to see exactly what went wrong." buttons {"OK"} default button "OK" with icon caution
end try
