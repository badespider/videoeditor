import { useState } from 'react';
import { motion } from 'framer-motion';
import { 
  FileText, 
  Upload, 
  CheckCircle, 
  XCircle, 
  Loader2,
  Play,
  Clock
} from 'lucide-react';
import { matchScript } from '../api/client';

interface ScriptMatch {
  segment: {
    text: string;
    index: number;
  };
  matchedClip: {
    startTime: number;
    endTime: number;
    confidence: number;
  };
  alternatives: Array<{
    startTime: number;
    endTime: number;
    confidence: number;
  }>;
}

interface ScriptMatcherProps {
  videoId: string;
}

export default function ScriptMatcher({ videoId }: ScriptMatcherProps) {
  const [script, setScript] = useState('');
  const [matches, setMatches] = useState<ScriptMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matchingId, setMatchingId] = useState<string | null>(null);

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleUploadScript = async () => {
    if (!script.trim()) {
      setError('Please enter a script');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await matchScript(videoId, script);
      setMatches(result.matches);
      setMatchingId(result.matching_id);
    } catch (err: any) {
      setError(err.message || 'Failed to match script');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-6 bg-white rounded-lg shadow-lg">
      <h2 className="text-2xl font-bold mb-4 flex items-center gap-2">
        <FileText className="w-6 h-6" />
        Script-to-Clip Matching
      </h2>

      <div className="mb-6">
        <label className="block text-sm font-medium mb-2">
          Script Text
        </label>
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          placeholder="Paste your script here. Each paragraph will be matched to video clips..."
          className="w-full h-48 p-3 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          disabled={loading}
        />
      </div>

      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md flex items-center gap-2 text-red-700"
        >
          <XCircle className="w-5 h-5" />
          {error}
        </motion.div>
      )}

      <button
        onClick={handleUploadScript}
        disabled={loading || !script.trim()}
        className="w-full py-2 px-4 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            Finding Matching Clips...
          </>
        ) : (
          <>
            <Upload className="w-5 h-5" />
            Find Matching Clips
          </>
        )}
      </button>

      {matches.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-6 space-y-4"
        >
          <h3 className="text-xl font-semibold mb-4">Matched Clips</h3>
          
          {matches.map((match, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="p-4 border border-gray-200 rounded-lg hover:shadow-md transition-shadow"
            >
              <div className="mb-3">
                <p className="text-sm text-gray-600 mb-1">Segment {idx + 1}</p>
                <p className="text-gray-800">{match.segment.text}</p>
              </div>

              <div className="flex items-center gap-4 p-3 bg-blue-50 rounded-md">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Play className="w-4 h-4 text-blue-600" />
                    <span className="font-medium">Matched Clip</span>
                    <span className={`text-sm px-2 py-1 rounded ${
                      match.matchedClip.confidence >= 0.75
                        ? 'bg-green-100 text-green-700'
                        : match.matchedClip.confidence >= 0.65
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-red-100 text-red-700'
                    }`}>
                      {(match.matchedClip.confidence * 100).toFixed(0)}% confidence
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-gray-600">
                    <Clock className="w-4 h-4" />
                    {formatTime(match.matchedClip.startTime)} - {formatTime(match.matchedClip.endTime)}
                  </div>
                </div>
              </div>

              {match.matchedClip.confidence < 0.75 && match.alternatives.length > 0 && (
                <div className="mt-3">
                  <p className="text-sm text-gray-600 mb-2">Alternative Clips:</p>
                  <div className="space-y-2">
                    {match.alternatives.map((alt, altIdx) => (
                      <div
                        key={altIdx}
                        className="p-2 bg-gray-50 rounded text-sm flex items-center justify-between"
                      >
                        <span>
                          {formatTime(alt.startTime)} - {formatTime(alt.endTime)}
                        </span>
                        <span className="text-gray-500">
                          {(alt.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );
}

