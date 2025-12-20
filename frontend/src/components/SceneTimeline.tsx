import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Clock, MessageSquare, Image as ImageIcon } from 'lucide-react';
import { getScenes, Scene } from '../api/client';

interface SceneTimelineProps {
  jobId: string;
}

export default function SceneTimeline({ jobId }: SceneTimelineProps) {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedScene, setSelectedScene] = useState<number | null>(null);

  useEffect(() => {
    loadScenes();
  }, [jobId]);

  const loadScenes = async () => {
    try {
      const data = await getScenes(jobId);
      setScenes(data.scenes);
    } catch (error) {
      console.error('Failed to load scenes:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (loading) {
    return (
      <div className="glass rounded-2xl p-8 border border-dark-600/50">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-dark-600 rounded w-1/4" />
          <div className="grid grid-cols-4 gap-4">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="aspect-video bg-dark-600 rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-2xl p-6 border border-dark-600/50">
      <h3 className="font-display text-xl font-bold text-gray-200 mb-6 flex items-center gap-2">
        <Clock className="w-5 h-5 text-cyber-400" />
        Scene Timeline
        <span className="text-sm font-normal text-gray-500 ml-2">
          {scenes.length} scenes detected
        </span>
      </h3>

      {/* Timeline grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {scenes.map((scene, index) => (
          <motion.div
            key={scene.index}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: index * 0.05 }}
            onClick={() => setSelectedScene(selectedScene === scene.index ? null : scene.index)}
            className={`
              group cursor-pointer rounded-xl overflow-hidden
              border transition-all duration-300
              ${selectedScene === scene.index 
                ? 'border-cyber-400 ring-2 ring-cyber-400/30' 
                : 'border-dark-600 hover:border-cyber-600/50'
              }
            `}
          >
            {/* Thumbnail */}
            <div className="aspect-video bg-dark-700 relative overflow-hidden">
              {scene.thumbnail_url ? (
                <img
                  src={scene.thumbnail_url}
                  alt={`Scene ${scene.index + 1}`}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <ImageIcon className="w-8 h-8 text-dark-500" />
                </div>
              )}

              {/* Overlay with time */}
              <div className="absolute inset-0 bg-gradient-to-t from-dark-900/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              
              <div className="absolute bottom-2 left-2 right-2 flex justify-between items-center">
                <span className="text-xs font-medium text-white/90 bg-dark-900/60 px-2 py-0.5 rounded">
                  #{scene.index + 1}
                </span>
                <span className="text-xs text-white/80 bg-dark-900/60 px-2 py-0.5 rounded">
                  {formatTime(scene.start_time)} - {formatTime(scene.end_time)}
                </span>
              </div>
            </div>

            {/* Scene info */}
            <div className="p-3 bg-dark-800/50">
              <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
                <Clock className="w-3 h-3" />
                <span>{scene.duration.toFixed(1)}s</span>
              </div>

              {scene.narration && (
                <p className="text-xs text-gray-300 line-clamp-2">
                  {scene.narration}
                </p>
              )}
            </div>
          </motion.div>
        ))}
      </div>

      {/* Selected scene detail */}
      {selectedScene !== null && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-6 p-4 rounded-xl bg-dark-700/50 border border-cyber-600/30"
        >
          {(() => {
            const scene = scenes.find(s => s.index === selectedScene);
            if (!scene) return null;

            return (
              <div className="flex gap-6">
                {/* Thumbnail */}
                <div className="w-64 flex-shrink-0">
                  <div className="aspect-video rounded-lg overflow-hidden bg-dark-600">
                    {scene.thumbnail_url ? (
                      <img
                        src={scene.thumbnail_url}
                        alt={`Scene ${scene.index + 1}`}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <ImageIcon className="w-12 h-12 text-dark-500" />
                      </div>
                    )}
                  </div>
                </div>

                {/* Details */}
                <div className="flex-1 space-y-4">
                  <div>
                    <h4 className="font-display text-lg font-semibold text-gray-200">
                      Scene {scene.index + 1}
                    </h4>
                    <p className="text-sm text-gray-400">
                      {formatTime(scene.start_time)} - {formatTime(scene.end_time)} ({scene.duration.toFixed(1)}s)
                    </p>
                  </div>

                  {scene.narration && (
                    <div>
                      <div className="flex items-center gap-2 text-sm text-gray-400 mb-2">
                        <MessageSquare className="w-4 h-4" />
                        <span>Narration</span>
                      </div>
                      <p className="text-gray-300 text-sm leading-relaxed">
                        {scene.narration}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
        </motion.div>
      )}
    </div>
  );
}

