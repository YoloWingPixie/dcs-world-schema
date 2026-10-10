import { HomeSearch } from "@/components/home-search";
import { DataVersion, SeriesDirectory } from "@/components/series-directory";

export default function Home() {
  return (
    <div className="page">
      <section className="title-block" aria-labelledby="home-title">
        <h1 id="home-title">DCS World Reference</h1>
        <p className="title-sub">Unit, weapon and mission data, and the Lua scripting API</p>
        <DataVersion variant="home" />
        <HomeSearch />
      </section>

      <section className="contents-block" aria-labelledby="contents-title">
        <h2 className="chapter-head" id="contents-title">
          Contents
        </h2>
        <SeriesDirectory />
      </section>
    </div>
  );
}
