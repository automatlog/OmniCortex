"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Upload, Trash2, FileText, Eye } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { getAgent, getAgentDocuments, deleteDocument, uploadDocuments, type Agent } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Document {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  content_preview: string;
  chunk_count: number;
  uploaded_at: string;
  embedding_time: number;
}

export default function AgentDocumentsPage() {
  const params = useParams();
  const agentId = params.id as string;
  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);

  useEffect(() => {
    loadData();
  }, [agentId]);

  async function loadData() {
    try {
      const [agentData, docs] = await Promise.all([
        getAgent(agentId),
        fetch(`${process.env.NEXT_PUBLIC_API_URL}/agents/${agentId}/documents`)
          .then(r => r.json())
      ]);
      setAgent(agentData);
      setDocuments(docs);
    } catch (error) {
      console.error("Failed to load:", error);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload() {
    if (selectedFiles.length === 0) return;
    
    setUploading(true);
    try {
      await uploadDocuments(agentId, selectedFiles);
      setUploadOpen(false);
      setSelectedFiles([]);
      loadData();
    } catch (error) {
      console.error("Upload failed:", error);
      alert("Upload failed. Check console.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(docId: number) {
    if (!confirm("Delete this document?")) return;
    
    try {
      await deleteDocument(docId);
      loadData();
    } catch (error) {
      console.error("Delete failed:", error);
    }
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function getFileIcon(type: string) {
    const icons: Record<string, string> = {
      pdf: "📕",
      txt: "📄",
      csv: "📊",
      docx: "📘",
      text: "📝"
    };
    return icons[type] || "📄";
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[80vh]">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center h-[80vh]">
        <p className="text-lg mb-4">Agent not found</p>
        <Link href="/agents" className="text-blue-400 hover:underline">
          ← Back to Agents
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/agents"
            className="p-2 rounded-lg hover:bg-neutral-800 text-neutral-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-white">Documents</h1>
            <p className="text-sm text-neutral-400">
              {agent.name} • {documents.length} documents
            </p>
          </div>
        </div>

        <Button
          onClick={() => setUploadOpen(true)}
          className="bg-blue-600 hover:bg-blue-500"
        >
          <Upload className="w-4 h-4 mr-2" />
          Upload Documents
        </Button>
      </div>

      {/* Documents Grid */}
      {documents.length === 0 ? (
        <div className="text-center py-16 text-neutral-500">
          <FileText className="w-16 h-16 mx-auto mb-4 opacity-50" />
          <p className="text-lg">No documents uploaded yet</p>
          <Button
            onClick={() => setUploadOpen(true)}
            variant="outline"
            className="mt-4"
          >
            Upload your first document
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="bg-neutral-900 border border-neutral-800 rounded-lg p-4 hover:border-neutral-700 transition-colors"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">{getFileIcon(doc.file_type)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">
                      {doc.filename}
                    </p>
                    <p className="text-xs text-neutral-500">
                      {formatFileSize(doc.file_size)}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(doc.id)}
                  className="p-1 rounded hover:bg-red-500/20 text-neutral-400 hover:text-red-400 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-2 text-xs text-neutral-400">
                <div className="flex justify-between">
                  <span>Chunks:</span>
                  <span className="text-white">{doc.chunk_count}</span>
                </div>
                <div className="flex justify-between">
                  <span>Uploaded:</span>
                  <span className="text-white">
                    {new Date(doc.uploaded_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Embedding Time:</span>
                  <span className="text-white">{doc.embedding_time.toFixed(2)}s</span>
                </div>
              </div>

              {doc.content_preview && (
                <Button
                  onClick={() => setPreviewDoc(doc)}
                  variant="outline"
                  size="sm"
                  className="w-full mt-3"
                >
                  <Eye className="w-3 h-3 mr-2" />
                  Preview
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Upload Dialog */}
      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent className="bg-neutral-900 border-neutral-800">
          <DialogHeader>
            <DialogTitle className="text-white">Upload Documents</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <input
              type="file"
              multiple
              accept=".pdf,.txt,.docx,.csv"
              onChange={(e) => setSelectedFiles(Array.from(e.target.files || []))}
              className="block w-full text-sm text-neutral-400
                file:mr-4 file:py-2 file:px-4
                file:rounded-md file:border-0
                file:text-sm file:font-semibold
                file:bg-blue-600 file:text-white
                hover:file:bg-blue-500"
            />
            {selectedFiles.length > 0 && (
              <div className="text-sm text-neutral-400">
                {selectedFiles.length} file(s) selected
              </div>
            )}
            <div className="flex justify-end gap-3">
              <Button
                variant="outline"
                onClick={() => setUploadOpen(false)}
                className="border-neutral-700"
              >
                Cancel
              </Button>
              <Button
                onClick={handleUpload}
                disabled={selectedFiles.length === 0 || uploading}
                className="bg-blue-600 hover:bg-blue-500"
              >
                {uploading ? "Uploading..." : "Upload"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={!!previewDoc} onOpenChange={() => setPreviewDoc(null)}>
        <DialogContent className="bg-neutral-900 border-neutral-800 max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-white">
              {previewDoc?.filename}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-96 overflow-y-auto">
            <pre className="text-sm text-neutral-300 whitespace-pre-wrap">
              {previewDoc?.content_preview}
            </pre>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
