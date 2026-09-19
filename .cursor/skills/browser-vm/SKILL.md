---
name: browser-vm
description: >-
  Drive the QEMU chromebox Chrome from the listings research container (alias of
  browser-vm-remote / gbrowser). Use for chromebox, guest browser, shared Chrome
  tab, Yad2/Facebook pages that need a real headed browser, or captcha HITL.
  On captcha: STOP and hand off to the human at http://100.92.122.70:6081/ —
  do not re-probe in a loop.
---

# browser-vm — chromebox via `gbrowser`

Same tooling as **browser-vm-remote**. From `/root/work`:

```bash
gbrowser tunnel up
gbrowser ctl list
gbrowser ctl nav https://www.yad2.co.il/
gbrowser ctl snap
```

## Captcha (HITL) — do this first

If Yad2 shows Press & Hold / perfdrive / Radware:

1. **Stop** probing / opening new tabs.
2. Message the user: open **http://100.92.122.70:6081/** and clear captcha on the open tab.
3. Wait for confirmation; resume the **same** tab.

Full command table and HITL notes: see skill `browser-vm-remote`.
