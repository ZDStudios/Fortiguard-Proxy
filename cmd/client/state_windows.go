package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"
)

// Settings are what the app remembers between runs.
type Settings struct {
	Theme       string `json:"theme"`
	Links       int    `json:"links"`
	DownMbps    int    `json:"downMbps"` // 0 means unlimited
	UpMbps      int    `json:"upMbps"`
	DNS         string `json:"dns"`
	AllowQUIC   bool   `json:"allowQuic"`
	BlockIPv6   bool   `json:"blockIpv6"`
	AutoConnect bool   `json:"autoConnect"`
	FailSafe    bool   `json:"failSafe"` // turn off if the server is gone, so the internet keeps working
}

func defaultSettings() Settings {
	return Settings{Theme: "midnight", Links: 4, DNS: "1.1.1.1", BlockIPv6: true, FailSafe: true}
}

// sanitize keeps a settings file edited by hand from breaking the app.
func (s Settings) sanitize() Settings {
	d := defaultSettings()
	if !slices.Contains([]int{1, 2, 4, 8}, s.Links) {
		s.Links = d.Links
	}
	if !slices.Contains([]string{"1.1.1.1", "8.8.8.8", "9.9.9.9"}, s.DNS) {
		s.DNS = d.DNS
	}
	if !slices.Contains([]string{"midnight", "aurora", "ember", "graphite", "daylight", "sakura"}, s.Theme) {
		s.Theme = d.Theme
	}
	s.DownMbps = min(max(s.DownMbps, 0), 100000)
	s.UpMbps = min(max(s.UpMbps, 0), 100000)
	return s
}

func loadSettings(dir string) Settings {
	s := defaultSettings()
	if b, err := os.ReadFile(filepath.Join(dir, "settings.json")); err == nil {
		if err := json.Unmarshal(b, &s); err != nil {
			s = defaultSettings()
		}
	}
	return s.sanitize()
}

func saveSettings(dir string, s Settings) error {
	b, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	path := filepath.Join(dir, "settings.json")
	if err := os.WriteFile(path+".tmp", b, 0o600); err != nil {
		return err
	}
	return os.Rename(path+".tmp", path)
}

// LogEntry is one line in the Logs view.
type LogEntry struct {
	Seq   uint64 `json:"seq"`
	Time  string `json:"time"`
	Level string `json:"level"`
	Text  string `json:"text"`
}

// Logs keeps recent events for the app's Logs view and copies them to app.log.
type Logs struct {
	mu      sync.Mutex
	entries []LogEntry
	seq     uint64
}

const maxLogEntries = 1000

func (l *Logs) Add(level, format string, args ...any) {
	text := fmt.Sprintf(format, args...)
	log.Printf("[%s] %s", level, text)
	l.mu.Lock()
	defer l.mu.Unlock()
	l.seq++
	l.entries = append(l.entries, LogEntry{Seq: l.seq, Time: time.Now().Format("15:04:05"), Level: level, Text: text})
	if len(l.entries) > maxLogEntries {
		l.entries = slices.Clone(l.entries[len(l.entries)-maxLogEntries:])
	}
}

// Since returns entries newer than seq.
func (l *Logs) Since(seq uint64) []LogEntry {
	l.mu.Lock()
	defer l.mu.Unlock()
	out := []LogEntry{}
	for _, e := range l.entries {
		if e.Seq > seq {
			out = append(out, e)
		}
	}
	return out
}

func (l *Logs) Clear() {
	l.mu.Lock()
	l.entries = nil
	l.mu.Unlock()
}
