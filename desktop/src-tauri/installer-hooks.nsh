!macro NSIS_HOOK_PREINSTALL
  ; Remove legacy or stale WebView2 EBWebView cache on install or upgrade
  ; to prevent old cached assets/service worker icons from persisting.
  RMDir /r "$LOCALAPPDATA\ai.nexttutorbot.desktop\EBWebView"
  RMDir /r "$LOCALAPPDATA\ai.nanobot.desktop\EBWebView"
!macroend
