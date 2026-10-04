import Link from "next/link";
import { HomeSearch } from "@/components/home-search";
import { DataVersion, SeriesDirectory } from "@/components/series-directory";
import { NAV_SECTIONS } from "@/lib/nav";

export default function Home() {
  const others = NAV_SECTIONS.filter((s) => s.id !== "reference");
  return (
    <div className="page">
      <section className="home-hero" aria-labelledby="home-title">
        <h1 id="home-title">Look up anything in DCS World</h1>
        <p className="lede">
          Aircraft, weapons, sensors, stores, airbases and the rest, read from the game's own files.
          Search by name, nickname or DCS id, follow the links between records, and right-click any
          value to compare it.
        </p>
        <HomeSearch />
        <DataVersion variant="home" />
      </section>

      {others.length ? (
        <nav className="home-sections-nav" aria-label="Sections">
          {others.map((s) => (
            <Link key={s.id} href={s.href} className="series-card">
              <span className="series-card-name">{s.label}</span>
              <span className="series-card-blurb">{s.description}</span>
            </Link>
          ))}
        </nav>
      ) : null}

      <SeriesDirectory />
    </div>
  );
}
