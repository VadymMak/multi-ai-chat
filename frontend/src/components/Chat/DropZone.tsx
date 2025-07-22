import React from "react";
import { useDropzone } from "react-dropzone";

interface DropZoneProps {
  onFileDrop: (file: File) => void;
}

const DropZone: React.FC<DropZoneProps> = ({ onFileDrop }) => {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        onFileDrop(acceptedFiles[0]);
      }
    },
    multiple: false,
    accept: {
      "text/plain": [".txt"],
      "application/pdf": [".pdf"],
      "text/csv": [".csv"],
      "application/json": [".json"]
    }
  });

  return (
    <div
      {...getRootProps()}
      className="border border-dashed border-gray-400 rounded-lg p-4 text-center cursor-pointer bg-gray-50 hover:bg-gray-100"
    >
      <input {...getInputProps()} />
      {isDragActive ? (
        <p className="text-blue-500">Drop the file here…</p>
      ) : (
        <p className="text-gray-600">📎 Drag & drop a file here, or click to upload</p>
      )}
    </div>
  );
};

export default DropZone;
