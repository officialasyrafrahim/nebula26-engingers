import type { Contract, ContractResult } from "../api/types";
import { formatDate, formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ContractTableProps {
  results: ContractResult[];
  contracts: Contract[];
  scenario: string;
}

export default function ContractTable({
  results,
  contracts,
  scenario,
}: ContractTableProps) {
  const byNumber = new Map(contracts.map((contract) => [contract.contract_number, contract]));
  const ordered = [...results].sort((a, b) =>
    a.contract_number.localeCompare(b.contract_number),
  );
  const overrunning = ordered.filter((row) => row.overrun_days > 0).length;
  const maxOverrun = ordered.reduce(
    (max, row) => Math.max(max, row.overrun_days),
    0,
  );
  const totalOverrun = ordered.reduce((sum, row) => sum + row.overrun_days, 0);

  return (
    <Panel
      title="Contract completion & overrun"
      eyebrow={`Scenario ${scenario} · RESULTS.csv`}
      tone={overrunning > 0 ? "danger" : "ok"}
      actions={
        <span className="panel__meter">
          {overrunning}/{ordered.length} overrunning
        </span>
      }
    >
      <ul className="counts counts--wide" aria-label="Contract completion summary">
        <li className="counts__cell">
          <span className="counts__value">{ordered.length}</span>
          <span className="counts__label">Contracts scored</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{ordered.length - overrunning}</span>
          <span className="counts__label">On or before planned date</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{formatNumber(totalOverrun)}</span>
          <span className="counts__label">Total overrun days</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{formatNumber(maxOverrun)}</span>
          <span className="counts__label">Worst single overrun</span>
        </li>
      </ul>

      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">
            Simulated contract completion dates and overrun against planned dates
          </caption>
          <thead>
            <tr>
              <th scope="col">Contract</th>
              <th scope="col">Description</th>
              <th scope="col">Tier</th>
              <th scope="col">Planned</th>
              <th scope="col">Simulated</th>
              <th scope="col">Overrun</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((row) => {
              const contract = byNumber.get(row.contract_number);
              const late = row.overrun_days > 0;
              return (
                <tr key={row.id}>
                  <th scope="row">
                    <code>{row.contract_number}</code>
                  </th>
                  <td className="cell--wrap">
                    {contract?.contract_description ?? "—"}
                    <span className="cell__sub">
                      {contract
                        ? `${contract.activity_type} · ${contract.access_type} access`
                        : ""}
                    </span>
                  </td>
                  <td>{contract ? `T${contract.contract_priority}` : "—"}</td>
                  <td>{formatDate(contract?.planned_completion_date)}</td>
                  <td>{formatDate(row.simulated_completion_date)}</td>
                  <td className={late ? "cell--danger" : ""}>
                    {late ? `+${row.overrun_days} d` : "on time"}
                  </td>
                  <td>
                    <span className="cell__status">
                      <SignalLamp
                        tone={late ? "danger" : "ok"}
                        size="sm"
                        label={late ? `${row.overrun_days} days late` : "On time"}
                      />
                      {late ? "late" : "clear"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
