import React from "react";
import { FileText } from "lucide-react";

export function AggregateDiffChip({
  additions,
  deletions,
  files,
  onClick,
}: {
  additions: number;
  deletions: number;
  files: number;
  onClick?: () => void;
}) {
  if (!files) return null;
  const Tag = onClick ? "button" : "span";
  return (
    <Tag type={onClick ? "button" : undefined} className="aggregateDiffChip" onClick={onClick} title={`${files} 处文件改动`}>
      <FileText size={12} />
      <span>{files} 个文件</span>
      {additions > 0 && <span className="deltaAdd">+{additions}</span>}
      {deletions > 0 && <span className="deltaDel">-{deletions}</span>}
    </Tag>
  );
}
