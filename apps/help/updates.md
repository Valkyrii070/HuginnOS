# Software Update
Keeps the system, your apps, this computer's firmware and Huginn up to date. It's in Settings.

## What it updates
System: Ubuntu's packages, which include the kernel, drivers and the engine the Huginn browser uses. Apps: everything from Flathub. Firmware: the computer's own firmware and devices that take updates. Huginn: the browser, straight from its own repository.

## Update now
Check Now looks for updates; Update All puts everything in. Each group also has its own Update button. Updates marked Security fix a security problem: put those in soon. The system asks for your password before changing system packages.

## Automatic updates
On by default. Every few hours Huginn looks for updates. Apps and Huginn update by themselves at once. System updates are downloaded and go in the next time you restart, so nothing changes under a program you're using.

## Restarting
When something needs a restart to start being used (the kernel, firmware), a banner says so. Restart when it suits you.

## Going back
If a newer Huginn gives you trouble, Go Back returns to the version before. The version that came with the system is always kept.

## Restore points
Before every update, Huginn OS keeps a copy of the system as it was (the apps, drivers and settings, not your files), at most one every ten minutes. The newest six are kept, and the ones you make yourself (Make One) stay until you remove them. If an update gives you trouble, press Go Back to This beside one and restart: the system is as it was then, and your files in your home folder are untouched. If the computer won't start at all, pick "Huginn OS restore points" in the start-up menu (hold Shift, or press Escape, as it starts) and choose one. Going back keeps what you had before, in case you want it back; once everything works, remove it under Restore points to free the space. Restore points need Huginn OS installed by its own installer, which puts the system on btrfs.

## In the App Store
The App Store's Updates page lists just your apps, with an Update button for each.
