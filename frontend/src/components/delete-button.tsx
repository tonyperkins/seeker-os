"use client";

import { useState, useCallback } from "react";
import { Trash2, Loader2, AlertCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface DeleteButtonProps {
  onDelete: () => Promise<void>;
  itemName: string;
  itemId?: string | number;
  size?: "sm" | "default" | "icon" | "icon-sm";
  variant?: "ghost" | "outline" | "destructive";
  label?: string;
  triggerClassName?: string;
}

export function DeleteButton({
  onDelete,
  itemName,
  itemId,
  size = "sm",
  variant = "ghost",
  label,
  triggerClassName,
}: DeleteButtonProps) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDelete = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setDeleting(true);
    setError(null);
    try {
      await onDelete();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setDeleting(false);
    }
  }, [onDelete]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            size={size}
            variant={variant}
            className={triggerClassName}
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              setOpen(true);
            }}
          >
            <Trash2 className={size === "icon" || size === "icon-sm" ? "size-4" : "size-3.5"} />
            {label}
          </Button>
        }
      />
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Delete {itemName}?</DialogTitle>
          <DialogDescription>
            This action cannot be undone.{" "}
            {itemId !== undefined && (
              <>
                <span className="font-mono font-medium">{itemId}</span> will be permanently removed.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={deleting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
