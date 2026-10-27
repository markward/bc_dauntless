BC DAUNTLESS
============

A brand-new engine for Star Trek: Bridge Commander.

BC Dauntless replaces the original game engine with a modern one built from
scratch, then runs Bridge Commander's own game content on top of it. You
still need your own copy of Bridge Commander. Nothing from the original game
is included in this download.

This is an early build. Expect rough edges, and please tell us when you find
one (see "Found a problem?" below).


WHAT YOU NEED
-------------

BC Dauntless is developed on a MacBook Pro with an Apple M3 Pro chip
(11-core CPU, 14-core GPU, 36 GB of memory). The PC specs below are our
estimate of equivalent hardware. They haven't all been tested yet, so
treat them as a guide.

Minimum (roughly matches our development machine):
  - Windows 10 or 11, 64-bit
  - CPU: Intel Core i5-12400 or AMD Ryzen 5 5600X
  - GPU: NVIDIA GeForce GTX 1660 Super or AMD Radeon RX 5600 XT, with
    support for OpenGL 4.1 (any card from the last several years has it)
  - Memory: 16 GB

Recommended (smooth at high settings and high resolutions):
  - CPU: Intel Core i7-13700 or AMD Ryzen 7 7700X
  - GPU: NVIDIA GeForce RTX 3060 Ti or AMD Radeon RX 6700 XT
  - Memory: 16 GB or more

Fast single-core CPU speed matters more than core count: much of the game
runs on one core.

And two things from Bridge Commander itself:
  - A retail copy of Star Trek: Bridge Commander, installed
  - The Bridge Commander SDK, version 1.1. It's free and widely mirrored
    on community sites:
      https://www.google.com/search?q=bridge+commander+sdk+download


GETTING STARTED
---------------

1. Install Bridge Commander from your retail copy. Use a CLEAN install:
   see "Use a clean copy of Bridge Commander" below.

2. Download the Bridge Commander SDK 1.1 and unpack it anywhere. You need
   the folder that contains "Build".

3. Download the latest BC Dauntless zip from GitHub Releases:
       https://github.com/markward/bc_dauntless/releases
   Unzip it anywhere you like, for example your Documents folder. Do NOT
   unzip it into your Bridge Commander folder.

4. Run "BC Dauntless.exe".

5. The first time you start it, a "Select Bridge Commander Install" screen
   asks for two folders:
     - Game folder: your Bridge Commander install, the folder that
       contains "data".
     - SDK folder: the SDK you unpacked, the folder that contains "Build".
   Pick each with Browse. Each says "Bridge Commander install found" when
   it's right; then press Continue. You only do this once.

Your settings, saves and mods are kept in your own user folders, not in the
BC Dauntless folder:
  - Settings, saves and mods:  %APPDATA%\Dauntless
  - Log file:                  %LOCALAPPDATA%\Dauntless\Logs\dauntless.log

(Paste either path into the File Explorer address bar to open it.)


USE A CLEAN COPY OF BRIDGE COMMANDER
------------------------------------

Please point BC Dauntless at an UNMODIFIED Bridge Commander install.

BC Dauntless loads models, textures and sounds straight from your Bridge
Commander folder. If that folder has been modded, changed files get mixed
into the game in ways we can't detect or support, and the result is very
hard to tell apart from a bug in BC Dauntless.

If your current install is modded, install a second, untouched copy just for
BC Dauntless. Mods go somewhere else entirely: see MODDING.txt.


WHAT'S IN THIS BUILD
--------------------

  - A completely new game engine and renderer for Bridge Commander.

  - Upgraded ships: sharper registry names on the hull, new light emitters
    and light volumes, navigation lights, and animations on the Klingon
    Bird of Prey.

  - Whole star systems: regions of the same star system are now loaded into
    one map together, and you can fly between them.

  - Upgraded asteroids and space environments, including how asteroids
    break apart when destroyed.

  - Better bridges: improved models and materials, and a completely
    overhauled lighting system.

  - A new Quick Battle setup, built to cope with the huge numbers of ships
    the community has made. You can now put ships into groups, and choose
    when each group warps into the battle.


STILL TO COME
-------------

  - An overhaul of the Sovereign bridge.
  - A universe that feels more alive in free roam.
  - More victory conditions in Quick Battle.
  - More tweaks and improvements to ships.
  - Full mod support (early support is in; see MODDING.txt).
  - Restoring the Campaign.


FOUND A PROBLEM?
----------------

Report it on GitHub:

    https://github.com/markward/bc_dauntless/issues

Before opening a new issue, please search the existing ones. If someone has
already reported your problem, add a comment or a thumbs-up to theirs
instead of opening a duplicate. That keeps all the details in one place and
helps us see what matters most.

A good report says:
  - what you were doing,
  - what you expected to happen, and what happened instead,
  - whether you can make it happen again, and how.

Please attach your log file (%LOCALAPPDATA%\Dauntless\Logs\dauntless.log).
It records exactly which build you're running. Screenshots help too.


LICENSE
-------

BC Dauntless is free software, released under the GNU General Public
License version 3 (GPLv3). The full text is in LICENSE.txt.

In short (this summary is not the license itself):
  - You can use BC Dauntless for free, for any purpose.
  - You can share copies, changed or unchanged, with anyone.
  - If you share it, you must keep it under the same license and make the
    source code available too, so others get the same freedoms you did.
  - It comes with no warranty.

The GPL covers BC Dauntless only. Star Trek: Bridge Commander and its SDK
remain the property of their owners and are not covered by it.

The source code is at https://github.com/markward/bc_dauntless


CREDITS
-------

  - Mark Ward, for the modelling work on the bridges.
  - Tobias Weimann, for the LCARS designs.
  - The Antonio font, by Vernon Adams.
  - NifTools (NifLib and NifSkope) and OpenMW, whose work on the NIF format
    was our starting point for reading Bridge Commander's models.

BC Dauntless also includes other open-source software. Each one, and its
license, is listed in THIRD_PARTY_NOTICES.txt, and the full license texts
are in the "licenses" folder.


SHOW US SOME LOVE
-----------------

If you enjoy BC Dauntless, the best way to help is to subscribe to our
YouTube channel and share it:

    https://www.youtube.com/@BCDauntless

News and more on the website:

    https://bc-dauntless.netlify.app/


LEGAL
-----

THIS MATERIAL IS NOT MADE OR SUPPORTED BY ACTIVISION.

Created by Mark Ward (https://github.com/markward/bc_dauntless).

BC Dauntless is an independent project. It is not made by, affiliated with,
or supported by Activision or Paramount. It does not include any game
assets, scripts or other content from Star Trek: Bridge Commander. A
legitimate retail copy of Star Trek: Bridge Commander is required to use it.
