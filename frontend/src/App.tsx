import { useEffect, useState } from "react";
import { healthCheck } from "./api/client";

export default function App() {
  const [status, setStatus] = useState("checking backend...");

  useEffect(() => {
    healthCheck()
      .then((health) => setStatus(`backend ok: ${JSON.stringify(health)}`))
      .catch((error: Error) => setStatus(`backend unavailable: ${error.message}`));
  }, []);

  return (
    <main>
      <h1>Rail Maintenance Intelligence — Planner UI (skeleton)</h1>
      <p>
        This placeholder consumes the RMIS API under <code>/api/v1</code>. Views for
        assets, work packages, planning jobs and proposals are not wired yet.
      </p>
      <p>{status}</p>
    </main>
  );
}
