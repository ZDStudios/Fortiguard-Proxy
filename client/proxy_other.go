//go:build !windows

package main

// Stubs so the client still builds and runs on non-Windows systems (handy for
// testing the tunnel). The self-healing proxy logic is Windows-only.

func installExitCleanup()  {}
func spawnGuardian()       {}
func clearProxyIfOurs()    {}
func runGuardian([]string) {}
