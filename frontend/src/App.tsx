import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Film, Zap, Sparkles } from 'lucide-react';
import VideoUpload from './components/VideoUpload';
import JobProgress from './components/JobProgress';
import SceneTimeline from './components/SceneTimeline';
import VideoPreview from './components/VideoPreview';
import { listJobs, JobProgress as JobProgressType } from './api/client';

type View = 'upload' | 'processing' | 'preview';

function App() {
  const [currentView, setCurrentView] = useState<View>('upload');
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobProgressType[]>([]);
  const [isConnected, setIsConnected] = useState(true);

  const loadJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      setJobs(data);
      setIsConnected(true);
    } catch (error) {
      console.error('Failed to load jobs:', error);
      setIsConnected(false);
    }
  }, []);

  useEffect(() => {
    loadJobs();
    // Poll more frequently for real-time feel
    const interval = setInterval(loadJobs, 2000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  const handleUploadComplete = (jobId: string) => {
    setCurrentJobId(jobId);
    setCurrentView('processing');
    loadJobs();
  };

  const handleJobComplete = () => {
    setCurrentView('preview');
    loadJobs();
  };

  const handleBack = () => {
    setCurrentView('upload');
    setCurrentJobId(null);
  };

  const handleSelectJob = (jobId: string, status: string) => {
    setCurrentJobId(jobId);
    if (status === 'completed') {
      setCurrentView('preview');
    } else if (status === 'failed') {
      setCurrentView('upload');
    } else {
      setCurrentView('processing');
    }
  };

  return (
    <div className="min-h-screen grid-bg overflow-x-hidden">
      {/* Header */}
      <header className="border-b border-dark-600/50 glass sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <motion.div 
              className="flex items-center gap-3 cursor-pointer"
              onClick={handleBack}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              <div className="relative">
                <Film className="w-10 h-10 text-cyber-400" />
                <Sparkles className="w-4 h-4 text-neon-pink absolute -top-1 -right-1 animate-pulse" />
              </div>
              <div>
                <h1 className="font-display text-2xl font-bold tracking-wider text-glow text-cyber-400">
                  ANIME RECAP
                </h1>
                <p className="text-xs text-gray-500 font-medium tracking-widest">
                  STUDIO v1.0
                </p>
              </div>
            </motion.div>

            <div className="flex items-center gap-6">
              {/* Connection status */}
              <div className="flex items-center gap-2 text-sm">
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-neon-green animate-pulse' : 'bg-red-500'}`} />
                <span className={isConnected ? 'text-gray-400' : 'text-red-400'}>
                  {isConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>

              <nav className="flex items-center gap-4">
                <NavButton 
                  active={currentView === 'upload'} 
                  onClick={() => setCurrentView('upload')}
                >
                  Upload
                </NavButton>
                <NavButton 
                  active={currentView === 'processing'} 
                  onClick={() => currentJobId && setCurrentView('processing')}
                  disabled={!currentJobId}
                >
                  Processing
                </NavButton>
                <NavButton 
                  active={currentView === 'preview'} 
                  onClick={() => currentJobId && setCurrentView('preview')}
                  disabled={!currentJobId}
                >
                  Preview
                </NavButton>
              </nav>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8 overflow-x-hidden">
        <AnimatePresence mode="wait">
          {currentView === 'upload' && (
            <motion.div
              key="upload"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
            >
              <VideoUpload 
                onUploadComplete={handleUploadComplete}
                recentJobs={jobs}
                onSelectJob={handleSelectJob}
              />
            </motion.div>
          )}

          {currentView === 'processing' && currentJobId && (
            <motion.div
              key="processing"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
            >
              <JobProgress 
                jobId={currentJobId}
                onComplete={handleJobComplete}
                onBack={handleBack}
              />
            </motion.div>
          )}

          {currentView === 'preview' && currentJobId && (
            <motion.div
              key="preview"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3 }}
              className="space-y-8"
            >
              <VideoPreview jobId={currentJobId} />
              <SceneTimeline jobId={currentJobId} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Footer */}
      <footer className="border-t border-dark-600/30 mt-auto">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-center gap-2 text-sm text-gray-600">
            <Zap className="w-4 h-4 text-cyber-500" />
            <span>Powered by Memories.ai & ElevenLabs</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function NavButton({ 
  children, 
  active, 
  onClick, 
  disabled 
}: { 
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        px-4 py-2 font-medium text-sm tracking-wide transition-all duration-200 rounded-lg
        ${active 
          ? 'text-cyber-400 bg-cyber-400/10 border border-cyber-400/30' 
          : 'text-gray-400 hover:text-gray-200 hover:bg-dark-700'
        }
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      {children}
    </button>
  );
}

export default App;
