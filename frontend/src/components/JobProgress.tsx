import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Loader2, 
  CheckCircle, 
  XCircle, 
  ArrowLeft,
  Scissors,
  Eye,
  Mic,
  Film,
  Sparkles,
  Upload,
  Wifi,
  WifiOff
} from 'lucide-react';
import { getJobStatus, JobProgress as JobProgressType } from '../api/client';

interface JobProgressProps {
  jobId: string;
  onComplete: () => void;
  onBack: () => void;
}

const STAGES = [
  { key: 'pending', label: 'Queued', icon: Upload },
  { key: 'uploading', label: 'Uploading', icon: Upload },
  { key: 'processing', label: 'Processing', icon: Film },
  { key: 'detecting_scenes', label: 'Detecting Scenes', icon: Scissors },
  { key: 'generating_descriptions', label: 'Analyzing Video', icon: Eye },
  { key: 'generating_audio', label: 'Generating Narration', icon: Mic },
  { key: 'stitching', label: 'Creating Recap', icon: Sparkles },
  { key: 'completed', label: 'Complete', icon: CheckCircle },
];

export default function JobProgress({ jobId, onComplete, onBack }: JobProgressProps) {
  const [job, setJob] = useState<JobProgressType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Initial fetch
    fetchJob();

    // Try WebSocket connection
    connectWebSocket();

    // Also start polling as backup
    startPolling();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [jobId]);

  const connectWebSocket = () => {
    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/jobs/${jobId}/ws`);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        console.log('WS message:', message);
        setLastUpdate(new Date());
        
        if (message.type === 'update' || message.type === 'initial') {
          setJob(message.data);
          
          if (message.data.status === 'completed') {
            setTimeout(onComplete, 1500);
          } else if (message.data.status === 'failed') {
            setError(message.data.error_message || 'Processing failed');
          }
        } else if (message.type === 'complete') {
          setJob(message.data);
          setTimeout(onComplete, 1500);
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        setWsConnected(false);
      };

      ws.onclose = () => {
        console.log('WebSocket closed');
        setWsConnected(false);
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to connect WebSocket:', err);
      setWsConnected(false);
    }
  };

  const fetchJob = async () => {
    try {
      const data = await getJobStatus(jobId);
      setJob(data);
      setLastUpdate(new Date());
      
      if (data.status === 'completed') {
        setTimeout(onComplete, 1500);
      } else if (data.status === 'failed') {
        setError(data.error_message || 'Processing failed');
      }
    } catch (err) {
      console.error('Failed to fetch job:', err);
    }
  };

  const startPolling = () => {
    // Poll every 2 seconds
    pollIntervalRef.current = setInterval(fetchJob, 2000);
  };

  const getCurrentStageIndex = () => {
    if (!job) return -1;
    return STAGES.findIndex(s => s.key === job.status);
  };

  const currentStageIndex = getCurrentStageIndex();
  const isComplete = job?.status === 'completed';
  const isFailed = job?.status === 'failed';

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Back button & Connection Status */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Upload</span>
        </button>
        
        <div className="flex items-center gap-2 text-sm">
          {wsConnected ? (
            <span className="flex items-center gap-1 text-neon-green">
              <Wifi className="w-4 h-4" />
              <span>Live</span>
            </span>
          ) : (
            <span className="flex items-center gap-1 text-yellow-500">
              <WifiOff className="w-4 h-4" />
              <span>Polling</span>
            </span>
          )}
          {lastUpdate && (
            <span className="text-gray-500">
              Updated {formatTimeAgo(lastUpdate)}
            </span>
          )}
        </div>
      </div>

      {/* Main progress card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass rounded-2xl p-8 border border-dark-600/50"
      >
        {/* Header */}
        <div className="text-center mb-8">
          <motion.div
            animate={{ 
              rotate: isComplete || isFailed ? 0 : 360,
              scale: [1, 1.05, 1]
            }}
            transition={{ 
              rotate: { duration: 2, repeat: isComplete || isFailed ? 0 : Infinity, ease: 'linear' },
              scale: { duration: 1, repeat: Infinity }
            }}
            className="inline-block mb-4"
          >
            {isComplete ? (
              <CheckCircle className="w-16 h-16 text-neon-green" />
            ) : isFailed ? (
              <XCircle className="w-16 h-16 text-red-500" />
            ) : (
              <Loader2 className="w-16 h-16 text-cyber-400" />
            )}
          </motion.div>

          <h2 className="font-display text-2xl font-bold text-gray-100 mb-2">
            {isComplete 
              ? 'Recap Complete!' 
              : isFailed
              ? 'Processing Failed'
              : 'Creating Your Recap'
            }
          </h2>
          
          <AnimatePresence mode="wait">
            <motion.p
              key={job?.current_step}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="text-cyber-400 font-medium text-lg"
            >
              {job?.current_step || 'Initializing...'}
            </motion.p>
          </AnimatePresence>
        </div>

        {/* Progress bar */}
        <div className="mb-8">
          <div className="flex justify-between text-sm text-gray-400 mb-2">
            <span>Progress</span>
            <motion.span
              key={job?.progress}
              initial={{ scale: 1.2 }}
              animate={{ scale: 1 }}
              className="font-mono font-bold text-cyber-400"
            >
              {Math.round(job?.progress || 0)}%
            </motion.span>
          </div>
          <div className="h-4 bg-dark-700 rounded-full overflow-hidden relative">
            <motion.div
              className="h-full bg-gradient-to-r from-cyber-600 via-cyber-400 to-neon-pink relative"
              initial={{ width: 0 }}
              animate={{ width: `${job?.progress || 0}%` }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            >
              {/* Animated shine effect */}
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-pulse" />
            </motion.div>
            
            {/* Pulse at the end of progress bar */}
            {!isComplete && !isFailed && (
              <motion.div
                className="absolute top-0 bottom-0 w-2 bg-white/50 rounded-full"
                style={{ left: `${job?.progress || 0}%` }}
                animate={{ opacity: [0.5, 1, 0.5] }}
                transition={{ duration: 1, repeat: Infinity }}
              />
            )}
          </div>
        </div>

        {/* Scene counter */}
        {job && (job.total_scenes ?? 0) > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mb-6 p-4 rounded-xl bg-dark-700/50 border border-dark-600"
          >
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Scenes Processed</span>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-display font-bold text-cyber-400">
                  {job.processed_scenes}
                </span>
                <span className="text-gray-500">/</span>
                <span className="text-xl text-gray-400">
                  {job.total_scenes}
                </span>
              </div>
            </div>
            <div className="mt-2 h-2 bg-dark-600 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-cyber-500"
                initial={{ width: 0 }}
                animate={{ 
                  width: `${(job?.total_scenes ?? 0) > 0 ? ((job?.processed_scenes ?? 0) / (job?.total_scenes ?? 1)) * 100 : 0}%` 
                }}
              />
            </div>
          </motion.div>
        )}

        {/* Stage indicators */}
        <div className="space-y-2">
          {STAGES.filter(s => s.key !== 'completed').map((stage, index) => {
            const Icon = stage.icon;
            const stageIndex = STAGES.findIndex(s => s.key === stage.key);
            const isActive = stageIndex === currentStageIndex;
            const isCompleteStage = stageIndex < currentStageIndex || isComplete;
            const isPending = stageIndex > currentStageIndex;

            return (
              <motion.div
                key={stage.key}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                className={`
                  flex items-center gap-4 p-3 rounded-xl transition-all duration-300
                  ${isActive ? 'bg-cyber-500/10 border border-cyber-500/30 scale-[1.02]' : ''}
                  ${isCompleteStage && !isActive ? 'opacity-50' : ''}
                  ${isPending ? 'opacity-30' : ''}
                `}
              >
                <div className={`
                  p-2 rounded-lg transition-all duration-300
                  ${isActive ? 'bg-cyber-500/20 text-cyber-400 shadow-lg shadow-cyber-500/20' : ''}
                  ${isCompleteStage && !isActive ? 'bg-neon-green/20 text-neon-green' : ''}
                  ${isPending ? 'bg-dark-600 text-gray-500' : ''}
                `}>
                  {isCompleteStage && !isActive ? (
                    <CheckCircle className="w-5 h-5" />
                  ) : isActive ? (
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    >
                      <Loader2 className="w-5 h-5" />
                    </motion.div>
                  ) : (
                    <Icon className="w-5 h-5" />
                  )}
                </div>

                <div className="flex-1">
                  <p className={`font-medium ${isActive ? 'text-cyber-300' : 'text-gray-300'}`}>
                    {stage.label}
                  </p>
                </div>

                {isActive && (
                  <motion.div
                    animate={{ opacity: [0.5, 1, 0.5] }}
                    transition={{ duration: 1.5, repeat: Infinity }}
                    className="flex gap-1"
                  >
                    <div className="w-2 h-2 rounded-full bg-cyber-400" />
                    <div className="w-2 h-2 rounded-full bg-cyber-400" />
                    <div className="w-2 h-2 rounded-full bg-cyber-400" />
                  </motion.div>
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Error message */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mt-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400"
            >
              <p className="font-medium mb-1">Error</p>
              <p className="text-sm">{error}</p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Success message */}
        <AnimatePresence>
          {isComplete && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="mt-6 p-4 rounded-lg bg-neon-green/10 border border-neon-green/30 text-neon-green text-center"
            >
              <p className="font-medium">Your recap is ready!</p>
              <p className="text-sm opacity-80">Redirecting to preview...</p>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Live activity log */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
        className="glass rounded-xl p-4 border border-dark-600/30"
      >
        <h3 className="font-display text-sm font-semibold text-gray-400 mb-3 flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-neon-green animate-pulse' : 'bg-yellow-500'}`} />
          Live Activity
        </h3>
        <div className="font-mono text-xs text-gray-500 space-y-1">
          <p>Job ID: {jobId.slice(0, 8)}...</p>
          <p>Status: <span className="text-cyber-400">{job?.status || 'unknown'}</span></p>
          <p>Progress: <span className="text-cyber-400">{job?.progress?.toFixed(1) || 0}%</span></p>
          {(job?.total_scenes ?? 0) > 0 && (
            <p>Scenes: <span className="text-cyber-400">{job?.processed_scenes ?? 0}/{job?.total_scenes ?? 0}</span></p>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function formatTimeAgo(date: Date): string {
  const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}
