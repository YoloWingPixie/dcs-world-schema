import { HomeSearch } from "@/components/home-search";
import { DataVersion, SeriesDirectory } from "@/components/series-directory";

export default function Home() {
  return (
    <div className="page">
      <section className="home-hero" aria-labelledby="home-title">
        <h1 id="home-title">DCS World Reference</h1>
        <HomeSearch />
        <DataVersion variant="home" />
      </section>

      <SeriesDirectory />
    </div>
  );
}
