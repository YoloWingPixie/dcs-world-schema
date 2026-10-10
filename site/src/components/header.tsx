"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { compareHref, useCompare } from "@/lib/compare-store";
import { currentSection, NAV_SECTIONS, type NavSection } from "@/lib/nav";
import { THEME_KEY } from "@/lib/theme";
import { setUnitSystem, useUnitSystem } from "@/lib/unit-system";
import { GitHubIcon, MoonIcon, SearchIcon, SunIcon } from "@/ui/icons";
import { openPalette } from "./command-palette";

const GITHUB_URL = "https://github.com/YoloWingPixie/dcs-world-schema";

type Theme = "light" | "dark";

function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => setTheme(currentTheme()), []);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={theme ? `Switch to ${next} theme` : "Switch theme"}
      title={theme ? `Switch to ${next} theme` : "Switch theme"}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          window.localStorage.setItem(THEME_KEY, next);
        } catch {
          // Storage blocked: the theme holds for this page view.
        }
        setTheme(next);
      }}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

/**
 * Metric / Imperial. Both labels are rendered; CSS on <html data-units> shows the active
 * one, so the toggle is right before hydration (no layout shift).
 */
function UnitsToggle() {
  const system = useUnitSystem();
  const imperial = system === "imperial";
  return (
    <>
      {/* Phones: one button that flips the system. */}
      <button
        type="button"
        className="units-compact"
        onClick={() => setUnitSystem(imperial ? "metric" : "imperial")}
        aria-label={`Switch to ${imperial ? "metric" : "imperial"} units`}
        title="Switch units"
      >
        <span className="units-compact-metric">kg·m</span>
        <span className="units-compact-imperial">lb·ft</span>
      </button>
      {/* biome-ignore lint/a11y/useSemanticElements: a two-state segmented switch */}
      <div className="seg-slash units-toggle" role="group" aria-label="Units">
        <button
          type="button"
          className="seg-btn units-metric"
          aria-pressed={!imperial}
          onClick={() => setUnitSystem("metric")}
          title="m, km, km/h, kg"
        >
          Metric
        </button>
        <span className="seg-sep" aria-hidden="true">
          /
        </span>
        <button
          type="button"
          className="seg-btn units-imperial"
          aria-pressed={imperial}
          onClick={() => setUnitSystem("imperial")}
          title="ft, nm, kt, lb"
        >
          Imperial
        </button>
      </div>
    </>
  );
}

/**
 * Each section's link: its href, or the compare selection's (`compareHref`) with its record
 * count for the compare section. Shared by the header's nav and its phone menu.
 */
function useNavLinks(): Array<{ section: NavSection; href: string; count: number }> {
  const compare = useCompare();
  return NAV_SECTIONS.map((section) =>
    section.compare
      ? { section, href: compareHref(compare), count: compare.records.length }
      : { section, href: section.href, count: 0 },
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const links = useNavLinks();
  const section = currentSection(pathname);
  const [mac, setMac] = useState(false);
  useEffect(() => setMac(/Mac|iPhone|iPad/.test(navigator.platform)), []);
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand" aria-label="Home">
          <span className="brand-name">DCS World Reference</span>
        </Link>
        <nav className="site-nav" aria-label="Main">
          {links.map(({ section: s, href, count }) => (
            <Link
              key={s.id}
              href={href}
              prefetch={s.prefetch ?? null}
              className={s.className}
              aria-current={section?.id === s.id ? "page" : undefined}
            >
              {s.label}
              {count ? (
                <span className="count-badge">
                  {" "}
                  ({count}
                  <span className="visually-hidden"> selected</span>)
                </span>
              ) : null}
            </Link>
          ))}
        </nav>
        <details className="nav-menu">
          <summary aria-label="Menu">
            <span aria-hidden="true">☰</span>
          </summary>
          <nav className="nav-menu-list" aria-label="Main">
            {links.map(({ section: s, href }) => (
              <Link
                key={s.id}
                href={href}
                prefetch={s.prefetch ?? null}
                aria-current={section?.id === s.id ? "page" : undefined}
                onClick={(e) => e.currentTarget.closest("details")?.removeAttribute("open")}
              >
                {s.label}
              </Link>
            ))}
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
              GitHub ↗
            </a>
          </nav>
        </details>
        <span className="header-spacer" />
        <button type="button" className="search-trigger" onClick={openPalette} aria-label="Search">
          <SearchIcon width={16} height={16} />
          <span className="search-trigger-text">Search</span>
          <span className="kbd">{mac ? "⌘K" : "Ctrl K"}</span>
        </button>
        <UnitsToggle />
        <a
          className="icon-btn header-github"
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Source on GitHub"
          title="Source on GitHub"
        >
          <GitHubIcon />
        </a>
        <ThemeToggle />
      </div>
    </header>
  );
}
