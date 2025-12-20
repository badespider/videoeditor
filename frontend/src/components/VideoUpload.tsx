import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Upload, 
  Film, 
  Clock, 
  CheckCircle, 
  XCircle, 
  Loader2,
  FileVideo,
  Trash2,
  RefreshCw,
  FileText,
  X,
  Shield,
  Users
} from 'lucide-react';
import { uploadVideo, listJobs, JobProgress, listSeries, SeriesInfo } from '../api/client';
import CharacterManager from './CharacterManager';

interface VideoUploadProps {
  onUploadComplete: (jobId: string) => void;
  recentJobs: JobProgress[];
  onSelectJob: (jobId: string, status: string) => void;
}

export default function VideoUpload({ onUploadComplete, recentJobs, onSelectJob }: VideoUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobProgress[]>(recentJobs);
  const [refreshing, setRefreshing] = useState(false);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const scriptInputRef = useRef<HTMLInputElement>(null);
  const [targetDurationMinutes, setTargetDurationMinutes] = useState<string>('');
  const [characterGuide, setCharacterGuide] = useState<string>('');
  const [enableSceneMatcher, setEnableSceneMatcher] = useState<boolean>(false);
  const [enableCopyrightProtection, setEnableCopyrightProtection] = useState<boolean>(false);
  const [seriesId, setSeriesId] = useState<string>('');
  const [showCharacterManager, setShowCharacterManager] = useState(false);
  const [availableSeries, setAvailableSeries] = useState<SeriesInfo[]>([]);
  const [filteredSeries, setFilteredSeries] = useState<SeriesInfo[]>([]);
  const [showSeriesDropdown, setShowSeriesDropdown] = useState(false);
  const seriesInputRef = useRef<HTMLDivElement>(null);

  // Auto-refresh jobs list
  useEffect(() => {
    setJobs(recentJobs);
  }, [recentJobs]);

  useEffect(() => {
    const interval = setInterval(refreshJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  // Fetch available series on mount
  useEffect(() => {
    const loadSeries = async () => {
      try {
        const series = await listSeries();
        setAvailableSeries(series);
      } catch (err) {
        console.error('Failed to load series:', err);
      }
    };
    loadSeries();
  }, []);

  // Filter series as user types
  useEffect(() => {
    if (!seriesId.trim()) {
      setFilteredSeries([]);
      setShowSeriesDropdown(false);
      return;
    }

    const query = seriesId.toLowerCase().trim();
    const filtered = availableSeries.filter(s => 
      s.series_id.toLowerCase().includes(query)
    );
    setFilteredSeries(filtered);
    setShowSeriesDropdown(filtered.length > 0);
  }, [seriesId, availableSeries]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (seriesInputRef.current && !seriesInputRef.current.contains(event.target as Node)) {
        setShowSeriesDropdown(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const refreshJobs = async () => {
    try {
      const data = await listJobs();
      setJobs(data);
    } catch (err) {
      console.error('Failed to refresh jobs:', err);
    }
  };

  const handleManualRefresh = async () => {
    setRefreshing(true);
    await refreshJobs();
    setTimeout(() => setRefreshing(false), 500);
  };

  const handleScriptSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Validate file type
      const ext = file.name.toLowerCase().split('.').pop();
      if (ext === 'txt' || ext === 'md') {
        setScriptFile(file);
        setError(null);
      } else {
        setError('Script must be a .txt or .md file');
      }
    }
  };

  const removeScript = () => {
    setScriptFile(null);
    if (scriptInputRef.current) {
      scriptInputRef.current.value = '';
    }
  };

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setUploadProgress(0);

    try {
      const targetDuration = targetDurationMinutes ? parseFloat(targetDurationMinutes) : undefined;
      
      // Normalize seriesId to lowercase for case-insensitive matching
      const normalizedSeriesId = seriesId ? seriesId.trim().toLowerCase() : undefined;
      
      const response = await uploadVideo(
        file, 
        (progress) => {
          setUploadProgress(progress);
        }, 
        scriptFile || undefined, 
        targetDuration,
        characterGuide || undefined,
        enableSceneMatcher,
        enableCopyrightProtection,
        normalizedSeriesId
      );
      
      onUploadComplete(response.job_id);
      // Clear all fields after successful upload
      setScriptFile(null);
      setTargetDurationMinutes('');
      setCharacterGuide('');
      setEnableSceneMatcher(false);
      setEnableCopyrightProtection(false);
      // Keep seriesId as user may want to upload another episode of the same series
      if (scriptInputRef.current) {
        scriptInputRef.current.value = '';
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }, [onUploadComplete, scriptFile, characterGuide, targetDurationMinutes, enableSceneMatcher, enableCopyrightProtection, seriesId]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'video/*': ['.mp4', '.mkv', '.avi', '.webm', '.mov']
    },
    maxFiles: 1,
    disabled: uploading
  });

  const handleDelete = async (e: React.MouseEvent, jobId: string) => {
    e.stopPropagation();
    try {
      // Find the job to get video_id
      const job = jobs.find(j => j.job_id === jobId);
      if (job) {
        // For now just refresh - the job will be cleaned up
        await refreshJobs();
      }
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-neon-green" />;
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />;
      case 'pending':
        return <Clock className="w-5 h-5 text-yellow-500" />;
      default:
        return <Loader2 className="w-5 h-5 text-cyber-400 animate-spin" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'border-neon-green/30 hover:border-neon-green/50 bg-neon-green/5';
      case 'failed':
        return 'border-red-500/30 hover:border-red-500/50 bg-red-500/5';
      case 'pending':
        return 'border-yellow-500/30 hover:border-yellow-500/50';
      default:
        return 'border-cyber-600/30 hover:border-cyber-500/50 bg-cyber-500/5';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'completed': return 'Complete';
      case 'failed': return 'Failed';
      case 'pending': return 'Queued';
      case 'processing': return 'Processing';
      case 'detecting_scenes': return 'Extracting Transcript';
      case 'generating_descriptions': return 'Hunting Visuals';
      case 'generating_audio': return 'Generating Voiceover';
      case 'stitching': return 'Elastic Stitching';
      default: return status;
    }
  };

  const dropzoneProps = getRootProps();

  return (
    <div className="space-y-8 overflow-hidden">
      {/* Upload Zone */}
      <div
        {...dropzoneProps}
        className={`
          relative overflow-hidden rounded-2xl border-2 border-dashed p-12
          transition-all duration-300 cursor-pointer
          ${isDragActive 
            ? 'border-cyber-400 bg-cyber-400/10' 
            : 'border-dark-500 hover:border-cyber-600 bg-dark-800/40'
          }
          ${uploading ? 'pointer-events-none' : ''}
        `}
      >
        <input {...getInputProps()} />
        
        {/* Background decoration */}
        <div className="absolute inset-0 opacity-30">
          <div className="absolute top-0 left-1/4 w-64 h-64 bg-cyber-500/20 rounded-full blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-48 h-48 bg-neon-pink/10 rounded-full blur-3xl" />
        </div>

        <div className="relative z-10 flex flex-col items-center gap-6">
          <motion.div
            animate={isDragActive ? { scale: 1.1, rotate: 5 } : { scale: 1, rotate: 0 }}
            transition={{ type: 'spring', stiffness: 300 }}
          >
            {uploading ? (
              <div className="relative">
                <Loader2 className="w-20 h-20 text-cyber-400 animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-sm font-bold text-cyber-300">{uploadProgress}%</span>
                </div>
              </div>
            ) : (
              <div className="p-6 rounded-full bg-gradient-to-br from-cyber-600/20 to-neon-pink/10 border border-cyber-500/30">
                <Upload className="w-12 h-12 text-cyber-400" />
              </div>
            )}
          </motion.div>

          <div className="text-center">
            <h2 className="text-2xl font-display font-bold text-gray-100 mb-2">
              {uploading ? 'Uploading...' : isDragActive ? 'Drop it here!' : 'Upload Your Anime Episode'}
            </h2>
            <p className="text-gray-400 max-w-md">
              {uploading 
                ? 'Please wait while your video is being uploaded'
                : 'Drag and drop your video file here, or click to browse. Supports MP4, MKV, AVI, WebM'
              }
            </p>
          </div>

          {!uploading && (
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <div className="flex items-center gap-2">
                <FileVideo className="w-4 h-4" />
                <span>Max 2GB</span>
              </div>
              <div className="w-1 h-1 rounded-full bg-gray-600" />
              <div className="flex items-center gap-2">
                <Film className="w-4 h-4" />
                <span>Any duration</span>
              </div>
            </div>
          )}
        </div>

        {/* Upload progress bar */}
        {uploading && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-dark-700">
            <motion.div
              className="h-full bg-gradient-to-r from-cyber-500 to-neon-pink"
              initial={{ width: 0 }}
              animate={{ width: `${uploadProgress}%` }}
              transition={{ duration: 0.3 }}
            />
          </div>
        )}
      </div>

      {/* Script Upload Section */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-neon-pink/10 border border-neon-pink/20">
            <FileText className="w-6 h-6 text-neon-pink" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              Custom Script (Optional)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              By default, the AI extracts dialogue from your video and rewrites it as dramatic narration. 
              Upload a custom script to override this and use your own story instead.
            </p>
            
            {scriptFile ? (
              <div className="flex items-center gap-3 p-3 rounded-lg bg-neon-pink/10 border border-neon-pink/30">
                <FileText className="w-5 h-5 text-neon-pink flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-200 truncate">{scriptFile.name}</p>
                  <p className="text-xs text-gray-400">{(scriptFile.size / 1024).toFixed(1)} KB</p>
                </div>
                <button
                  onClick={removeScript}
                  className="p-1.5 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-red-400 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <label className="flex items-center gap-3 p-3 rounded-lg border border-dashed border-dark-400 hover:border-neon-pink/50 cursor-pointer transition-colors">
                <input
                  ref={scriptInputRef}
                  type="file"
                  accept=".txt,.md"
                  onChange={handleScriptSelect}
                  className="hidden"
                />
                <Upload className="w-5 h-5 text-gray-400" />
                <span className="text-sm text-gray-400">
                  Click to upload script (.txt or .md)
                </span>
              </label>
            )}
          </div>
        </div>
      </div>

      {/* Character Guide Section */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
            <Film className="w-6 h-6 text-purple-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              Character Guide (Optional)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Help the AI identify characters by name. Without this, narration will say "the woman" or "the man" instead of character names.
            </p>
            
            <textarea
              value={characterGuide}
              onChange={(e) => setCharacterGuide(e.target.value)}
              placeholder={`Woman with mystical powers = The Ancient One\nSkeptical man = Doctor Strange\nBald villain = Kaecilius`}
              rows={4}
              className="w-full px-4 py-3 rounded-lg bg-dark-700 border border-dark-500 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 resize-none font-mono text-sm"
            />
            <p className="text-xs text-gray-500 mt-2">
              Format: "Description = Character Name" (one per line)
            </p>
          </div>
        </div>
      </div>

      {/* Series ID Section - For Character Persistence */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <Film className="w-6 h-6 text-amber-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              Series ID (Optional)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Link videos to the same series to remember characters across episodes. The AI will learn character names
              from previous episodes and use them consistently. Use the same ID for all episodes of a series.
            </p>
            
            <div className="relative flex gap-2" ref={seriesInputRef}>
              <div className="flex-1 relative">
                <input
                  type="text"
                  value={seriesId}
                  onChange={(e) => {
                    setSeriesId(e.target.value);
                    setShowSeriesDropdown(true);
                  }}
                  onFocus={() => {
                    if (filteredSeries.length > 0) {
                      setShowSeriesDropdown(true);
                    }
                  }}
                  placeholder="e.g., jujutsu-kaisen-s1, naruto-shippuden, my-hero-academia"
                  className="w-full px-4 py-2 rounded-lg bg-dark-700 border border-dark-500 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
                />
                {/* Autocomplete Dropdown */}
                <AnimatePresence>
                  {showSeriesDropdown && filteredSeries.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      transition={{ duration: 0.2 }}
                      className="absolute z-50 w-full mt-1 bg-dark-800 border border-dark-600 rounded-lg shadow-xl max-h-60 overflow-y-auto"
                    >
                      {filteredSeries.map((series) => (
                        <button
                          key={series.series_id}
                          type="button"
                          onClick={() => {
                            setSeriesId(series.series_id);
                            setShowSeriesDropdown(false);
                          }}
                          className="w-full px-4 py-3 text-left hover:bg-dark-700 transition-colors border-b border-dark-600 last:border-b-0"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-gray-200 font-medium">{series.series_id}</span>
                            <span className="text-xs text-gray-400">
                              {series.character_count} {series.character_count === 1 ? 'character' : 'characters'}
                            </span>
                          </div>
                          {series.last_updated && (
                            <p className="text-xs text-gray-500 mt-1">
                              Updated {new Date(series.last_updated).toLocaleDateString()}
                            </p>
                          )}
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
              {seriesId.trim() && (
                <button
                  onClick={() => setShowCharacterManager(true)}
                  className="px-4 py-2 rounded-lg bg-amber-500/20 border border-amber-500/30 text-amber-400 hover:bg-amber-500/30 transition-colors flex items-center gap-2 whitespace-nowrap"
                >
                  <Users className="w-4 h-4" />
                  Manage
                </button>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Use lowercase letters, numbers, and hyphens. Characters are saved for 30 days.
              {seriesId.trim() && ' Click "Manage" to view or add characters before processing.'}
            </p>
          </div>
        </div>
      </div>

      {/* Target Duration Section */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-cyber-500/10 border border-cyber-500/20">
            <Clock className="w-6 h-6 text-cyber-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              Target Recap Duration (Optional)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Specify your desired recap length. The system will select chapters to fit this duration (allows ~10% over).
              Leave empty for no limit. Examples: Movies ~25-30 min, Anime compilations ~60-240 min.
            </p>
            
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                step="1"
                value={targetDurationMinutes}
                onChange={(e) => setTargetDurationMinutes(e.target.value)}
                placeholder="e.g., 30 for 30 minutes"
                className="flex-1 px-4 py-2 rounded-lg bg-dark-700 border border-dark-500 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-cyber-500 focus:ring-1 focus:ring-cyber-500"
              />
              <span className="text-sm text-gray-400 whitespace-nowrap">minutes</span>
            </div>
          </div>
        </div>
      </div>

      {/* SceneMatcher Section */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-green-500/10 border border-green-500/20">
            <Film className="w-6 h-6 text-green-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              AI-Powered Clip Matching (Experimental)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Enable intelligent scene matching that finds the best video clips for each narration segment.
              Uses AI to match story beats to visuals instead of just using sequential timestamps.
              <span className="text-yellow-400"> ⚠️ May increase processing time.</span>
            </p>
            
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={enableSceneMatcher}
                  onChange={(e) => setEnableSceneMatcher(e.target.checked)}
                  className="sr-only"
                />
                <div className={`
                  w-11 h-6 rounded-full transition-colors duration-200
                  ${enableSceneMatcher ? 'bg-green-500' : 'bg-dark-600'}
                `}>
                  <div className={`
                    absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full
                    transition-transform duration-200
                    ${enableSceneMatcher ? 'translate-x-5' : 'translate-x-0'}
                  `} />
                </div>
              </div>
              <span className="text-sm text-gray-300 font-medium">
                {enableSceneMatcher ? 'SceneMatcher Enabled' : 'SceneMatcher Disabled'}
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Copyright Protection Section */}
      <div className="glass rounded-xl p-6 border border-dark-500">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-purple-500/10 border border-purple-500/20">
            <Shield className="w-6 h-6 text-purple-400" />
          </div>
          <div className="flex-1">
            <h3 className="font-display font-semibold text-gray-200 mb-1">
              Copyright Protection (Experimental)
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Splits clips into &lt;3 second segments and applies subtle visual transformations 
              (brightness, saturation, speed tweaks) to help evade copyright detection.
              <span className="text-purple-400"> 🔒 Recommended for content creators.</span>
            </p>
            
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={enableCopyrightProtection}
                  onChange={(e) => setEnableCopyrightProtection(e.target.checked)}
                  className="sr-only"
                />
                <div className={`
                  w-11 h-6 rounded-full transition-colors duration-200
                  ${enableCopyrightProtection ? 'bg-purple-500' : 'bg-dark-600'}
                `}>
                  <div className={`
                    absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full
                    transition-transform duration-200
                    ${enableCopyrightProtection ? 'translate-x-5' : 'translate-x-0'}
                  `} />
                </div>
              </div>
              <span className="text-sm text-gray-300 font-medium">
                {enableCopyrightProtection ? 'Protection Enabled' : 'Protection Disabled'}
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Error message */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Recent Jobs */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-lg font-semibold text-gray-300 flex items-center gap-2">
            <Clock className="w-5 h-5 text-cyber-500" />
            Recent Projects
            <span className="text-sm font-normal text-gray-500">
              ({jobs.length})
            </span>
          </h3>
          
          <button
            onClick={handleManualRefresh}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-cyber-400 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {jobs.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Film className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>No projects yet. Upload a video to get started!</p>
          </div>
        ) : (
          <div className="grid gap-3">
            {jobs.slice(0, 10).map((job, index) => (
              <motion.div
                key={job.job_id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: index * 0.03 }}
                onClick={() => onSelectJob(job.job_id, job.status)}
                className={`
                  glass rounded-xl p-4 cursor-pointer transition-all duration-200
                  border ${getStatusColor(job.status)}
                  hover:bg-dark-700/80 hover:border-cyber-500/50
                `}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-4 min-w-0">
                    <div className="relative flex-shrink-0">
                      {getStatusIcon(job.status)}
                      {job.status !== 'completed' && job.status !== 'failed' && job.status !== 'pending' && (
                        <span className="absolute -top-1 -right-1 w-2 h-2 bg-cyber-400 rounded-full animate-pulse" />
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium text-gray-200 truncate">
                        Job {job.job_id.slice(0, 8)}...
                      </p>
                      <div className="flex items-center gap-2 text-sm flex-wrap">
                        <span className={`
                          px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap
                          ${job.status === 'completed' ? 'bg-neon-green/20 text-neon-green' : ''}
                          ${job.status === 'failed' ? 'bg-red-500/20 text-red-400' : ''}
                          ${job.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' : ''}
                          ${!['completed', 'failed', 'pending'].includes(job.status) ? 'bg-cyber-500/20 text-cyber-400' : ''}
                        `}>
                          {getStatusLabel(job.status)}
                        </span>
                        <span className="text-gray-500 truncate">
                          {job.current_step}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0 ml-9 sm:ml-0">
                    {/* Progress indicator for active jobs */}
                    {job.status !== 'completed' && job.status !== 'failed' && (
                      <div className="flex items-center gap-2">
                        <div className="w-20 sm:w-32 h-2 bg-dark-700 rounded-full overflow-hidden">
                          <motion.div 
                            className="h-full bg-gradient-to-r from-cyber-500 to-cyber-400"
                            initial={{ width: 0 }}
                            animate={{ width: `${job.progress}%` }}
                            transition={{ duration: 0.5 }}
                          />
                        </div>
                        <span className="text-sm font-mono text-cyber-400 w-10 text-right">
                          {Math.round(job.progress)}%
                        </span>
                      </div>
                    )}

                    {/* Segment count for active jobs */}
                    {(job.total_scenes ?? 0) > 0 && (
                      <span className="text-xs text-gray-500 whitespace-nowrap hidden sm:inline">
                        {job.processed_scenes}/{job.total_scenes} segments
                      </span>
                    )}

                    <button
                      onClick={(e) => handleDelete(e, job.job_id)}
                      className="p-2 rounded-lg hover:bg-dark-600 text-gray-500 hover:text-red-400 transition-colors flex-shrink-0"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Character Manager Modal */}
      <AnimatePresence>
        {showCharacterManager && seriesId.trim() && (
          <CharacterManager
            seriesId={seriesId.trim().toLowerCase()}
            onClose={() => setShowCharacterManager(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
