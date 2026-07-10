"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface JobsPaginationProps {
  page: number;
  total: number;
  pageSize: number;
  displayedCount: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}

export function JobsPagination(props: JobsPaginationProps) {
  const { page, total, pageSize, displayedCount, loading, onPageChange } = props;

  if (displayedCount === 0) return null;

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex items-center justify-between gap-4">
      <p className="text-xs text-muted-foreground">
        Showing {(page - 1) * pageSize + 1}–{(page - 1) * pageSize + displayedCount} of {total} job{total !== 1 ? "s" : ""}.
      </p>
      {total > pageSize && (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft className="size-4" />
            Prev
          </Button>
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || loading}
            onClick={() => onPageChange(page + 1)}
          >
            Next
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
