import React from "react";

type DataTableProps = {
  children: React.ReactNode;
  minWidth?: number;
};

export default function DataTable({ children, minWidth = 760 }: DataTableProps) {
  return (
    <div className="vv-table-wrap">
      <table className="vv-data-table" style={{ minWidth }}>
        {children}
      </table>
    </div>
  );
}
