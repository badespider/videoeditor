import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Users,
  Plus,
  Edit2,
  Trash2,
  X,
  Save,
  AlertCircle,
  Loader2,
  User,
  Star,
  Shield,
  UserMinus,
  RefreshCw,
  ChevronDown
} from 'lucide-react';
import {
  Character,
  CharacterCreate,
  CharacterUpdate,
  getSeriesCharacters,
  addCharacter,
  updateCharacter,
  deleteCharacter as deleteCharacterApi,
  clearSeries
} from '../api/client';

interface CharacterManagerProps {
  seriesId: string;
  onClose: () => void;
}

type RoleType = 'protagonist' | 'antagonist' | 'supporting' | 'minor';

const roleConfig: Record<RoleType, { label: string; color: string; icon: typeof Star }> = {
  protagonist: { label: 'Protagonist', color: 'text-green-400 bg-green-500/20 border-green-500/30', icon: Star },
  antagonist: { label: 'Antagonist', color: 'text-red-400 bg-red-500/20 border-red-500/30', icon: Shield },
  supporting: { label: 'Supporting', color: 'text-blue-400 bg-blue-500/20 border-blue-500/30', icon: User },
  minor: { label: 'Minor', color: 'text-gray-400 bg-gray-500/20 border-gray-500/30', icon: UserMinus }
};

const getConfidenceColor = (confidence: number) => {
  if (confidence >= 0.8) return 'bg-green-500';
  if (confidence >= 0.5) return 'bg-yellow-500';
  return 'bg-red-500';
};

export default function CharacterManager({ seriesId, onClose }: CharacterManagerProps) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingCharacter, setEditingCharacter] = useState<Character | null>(null);
  const [isAddingNew, setIsAddingNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Form state
  const [formData, setFormData] = useState<CharacterCreate>({
    name: '',
    aliases: [],
    description: '',
    role: 'supporting',
    visual_traits: []
  });
  const [aliasInput, setAliasInput] = useState('');
  const [traitInput, setTraitInput] = useState('');

  const loadCharacters = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const chars = await getSeriesCharacters(seriesId);
      setCharacters(chars);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load characters');
    } finally {
      setLoading(false);
    }
  }, [seriesId]);

  useEffect(() => {
    loadCharacters();
  }, [loadCharacters]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadCharacters();
    setRefreshing(false);
  };

  const resetForm = () => {
    setFormData({
      name: '',
      aliases: [],
      description: '',
      role: 'supporting',
      visual_traits: []
    });
    setAliasInput('');
    setTraitInput('');
    setEditingCharacter(null);
    setIsAddingNew(false);
  };

  const startEdit = (character: Character) => {
    setEditingCharacter(character);
    setFormData({
      name: character.name,
      aliases: [...character.aliases],
      description: character.description,
      role: character.role,
      visual_traits: [...character.visual_traits]
    });
    setIsAddingNew(false);
  };

  const startAddNew = () => {
    resetForm();
    setIsAddingNew(true);
  };

  const handleAddAlias = () => {
    if (aliasInput.trim() && !formData.aliases?.includes(aliasInput.trim())) {
      setFormData(prev => ({
        ...prev,
        aliases: [...(prev.aliases || []), aliasInput.trim()]
      }));
      setAliasInput('');
    }
  };

  const handleRemoveAlias = (alias: string) => {
    setFormData(prev => ({
      ...prev,
      aliases: prev.aliases?.filter(a => a !== alias) || []
    }));
  };

  const handleAddTrait = () => {
    if (traitInput.trim() && !formData.visual_traits?.includes(traitInput.trim())) {
      setFormData(prev => ({
        ...prev,
        visual_traits: [...(prev.visual_traits || []), traitInput.trim()]
      }));
      setTraitInput('');
    }
  };

  const handleRemoveTrait = (trait: string) => {
    setFormData(prev => ({
      ...prev,
      visual_traits: prev.visual_traits?.filter(t => t !== trait) || []
    }));
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError('Character name is required');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      if (isAddingNew) {
        await addCharacter(seriesId, formData);
      } else if (editingCharacter) {
        const updates: CharacterUpdate = {};
        if (formData.name !== editingCharacter.name) updates.name = formData.name;
        if (JSON.stringify(formData.aliases) !== JSON.stringify(editingCharacter.aliases)) {
          updates.aliases = formData.aliases;
        }
        if (formData.description !== editingCharacter.description) {
          updates.description = formData.description;
        }
        if (formData.role !== editingCharacter.role) updates.role = formData.role;
        if (JSON.stringify(formData.visual_traits) !== JSON.stringify(editingCharacter.visual_traits)) {
          updates.visual_traits = formData.visual_traits;
        }
        
        if (Object.keys(updates).length > 0) {
          await updateCharacter(seriesId, editingCharacter.id, updates);
        }
      }

      await loadCharacters();
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save character');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (charId: string) => {
    if (!confirm('Are you sure you want to delete this character?')) return;

    try {
      setError(null);
      await deleteCharacterApi(seriesId, charId);
      await loadCharacters();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete character');
    }
  };

  const handleClearAll = async () => {
    if (!confirm(`Are you sure you want to delete ALL ${characters.length} characters for this series? This cannot be undone.`)) {
      return;
    }

    try {
      setError(null);
      await clearSeries(seriesId);
      await loadCharacters();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear series');
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="bg-dark-800 border border-dark-500 rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-dark-500">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/20 border border-amber-500/30">
              <Users className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h2 className="text-xl font-display font-bold text-gray-100">Character Manager</h2>
              <p className="text-sm text-gray-400">
                Series: <span className="text-amber-400 font-mono">{seriesId}</span>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-gray-200 transition-colors"
            >
              <RefreshCw className={`w-5 h-5 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-dark-600 text-gray-400 hover:text-gray-200 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Error Alert */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mx-6 mt-4 p-3 rounded-lg bg-red-500/20 border border-red-500/30 flex items-center gap-2 text-red-400"
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{error}</span>
              <button onClick={() => setError(null)} className="ml-auto">
                <X className="w-4 h-4" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-180px)]">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-amber-400 animate-spin" />
            </div>
          ) : (
            <>
              {/* Actions Bar */}
              <div className="flex items-center justify-between mb-6">
                <p className="text-sm text-gray-400">
                  {characters.length} character{characters.length !== 1 ? 's' : ''} saved
                </p>
                <div className="flex items-center gap-2">
                  {characters.length > 0 && (
                    <button
                      onClick={handleClearAll}
                      className="px-3 py-1.5 text-sm rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-colors"
                    >
                      Clear All
                    </button>
                  )}
                  <button
                    onClick={startAddNew}
                    className="px-3 py-1.5 text-sm rounded-lg bg-amber-500/20 border border-amber-500/30 text-amber-400 hover:bg-amber-500/30 transition-colors flex items-center gap-1.5"
                  >
                    <Plus className="w-4 h-4" />
                    Add Character
                  </button>
                </div>
              </div>

              {/* Add/Edit Form */}
              <AnimatePresence>
                {(isAddingNew || editingCharacter) && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mb-6 overflow-hidden"
                  >
                    <div className="p-4 rounded-xl bg-dark-700/50 border border-dark-500 space-y-4">
                      <h3 className="font-semibold text-gray-200">
                        {isAddingNew ? 'Add New Character' : `Edit: ${editingCharacter?.name}`}
                      </h3>

                      {/* Name */}
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Name *</label>
                        <input
                          type="text"
                          value={formData.name}
                          onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                          placeholder="e.g., Gojo Satoru"
                          className="w-full px-3 py-2 rounded-lg bg-dark-600 border border-dark-400 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500"
                        />
                      </div>

                      {/* Role */}
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Role</label>
                        <div className="relative">
                          <select
                            value={formData.role}
                            onChange={e => setFormData(prev => ({ ...prev, role: e.target.value as RoleType }))}
                            className="w-full px-3 py-2 rounded-lg bg-dark-600 border border-dark-400 text-gray-200 focus:outline-none focus:border-amber-500 appearance-none cursor-pointer"
                          >
                            <option value="protagonist">Protagonist</option>
                            <option value="antagonist">Antagonist</option>
                            <option value="supporting">Supporting</option>
                            <option value="minor">Minor</option>
                          </select>
                          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                        </div>
                      </div>

                      {/* Description */}
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Description</label>
                        <textarea
                          value={formData.description}
                          onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                          placeholder="Brief description of the character..."
                          rows={2}
                          className="w-full px-3 py-2 rounded-lg bg-dark-600 border border-dark-400 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500 resize-none"
                        />
                      </div>

                      {/* Aliases */}
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Aliases</label>
                        <div className="flex gap-2 mb-2">
                          <input
                            type="text"
                            value={aliasInput}
                            onChange={e => setAliasInput(e.target.value)}
                            onKeyPress={e => e.key === 'Enter' && (e.preventDefault(), handleAddAlias())}
                            placeholder="Add alias and press Enter"
                            className="flex-1 px-3 py-2 rounded-lg bg-dark-600 border border-dark-400 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500"
                          />
                          <button
                            onClick={handleAddAlias}
                            className="px-3 py-2 rounded-lg bg-dark-500 hover:bg-dark-400 text-gray-300 transition-colors"
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                        </div>
                        {formData.aliases && formData.aliases.length > 0 && (
                          <div className="flex flex-wrap gap-2">
                            {formData.aliases.map(alias => (
                              <span
                                key={alias}
                                className="px-2 py-1 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-xs flex items-center gap-1"
                              >
                                {alias}
                                <button onClick={() => handleRemoveAlias(alias)}>
                                  <X className="w-3 h-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Visual Traits */}
                      <div>
                        <label className="block text-sm text-gray-400 mb-1">Visual Traits</label>
                        <div className="flex gap-2 mb-2">
                          <input
                            type="text"
                            value={traitInput}
                            onChange={e => setTraitInput(e.target.value)}
                            onKeyPress={e => e.key === 'Enter' && (e.preventDefault(), handleAddTrait())}
                            placeholder="e.g., white hair, blindfold"
                            className="flex-1 px-3 py-2 rounded-lg bg-dark-600 border border-dark-400 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500"
                          />
                          <button
                            onClick={handleAddTrait}
                            className="px-3 py-2 rounded-lg bg-dark-500 hover:bg-dark-400 text-gray-300 transition-colors"
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                        </div>
                        {formData.visual_traits && formData.visual_traits.length > 0 && (
                          <div className="flex flex-wrap gap-2">
                            {formData.visual_traits.map(trait => (
                              <span
                                key={trait}
                                className="px-2 py-1 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-xs flex items-center gap-1"
                              >
                                {trait}
                                <button onClick={() => handleRemoveTrait(trait)}>
                                  <X className="w-3 h-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Form Actions */}
                      <div className="flex justify-end gap-2 pt-2">
                        <button
                          onClick={resetForm}
                          className="px-4 py-2 rounded-lg border border-dark-400 text-gray-400 hover:bg-dark-600 transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={handleSave}
                          disabled={saving || !formData.name.trim()}
                          className="px-4 py-2 rounded-lg bg-amber-500 text-dark-900 font-medium hover:bg-amber-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        >
                          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                          {isAddingNew ? 'Add Character' : 'Save Changes'}
                        </button>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Character List */}
              {characters.length === 0 ? (
                <div className="text-center py-12">
                  <Users className="w-16 h-16 mx-auto text-gray-600 mb-4" />
                  <p className="text-gray-400 mb-2">No characters saved yet</p>
                  <p className="text-sm text-gray-500">
                    Characters will be automatically extracted when you process videos with this series ID,
                    or you can add them manually.
                  </p>
                </div>
              ) : (
                <div className="grid gap-3">
                  {characters.map(character => {
                    const role = roleConfig[character.role] || roleConfig.supporting;
                    const RoleIcon = role.icon;
                    
                    return (
                      <motion.div
                        key={character.id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        className="p-4 rounded-xl bg-dark-700/50 border border-dark-500 hover:border-dark-400 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-2">
                              <h4 className="font-semibold text-gray-200 truncate">{character.name}</h4>
                              <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${role.color} flex items-center gap-1`}>
                                <RoleIcon className="w-3 h-3" />
                                {role.label}
                              </span>
                              {character.source_video_no === 'manual' && (
                                <span className="px-2 py-0.5 rounded-full text-xs bg-amber-500/20 border border-amber-500/30 text-amber-400">
                                  Manual
                                </span>
                              )}
                            </div>

                            {character.description && (
                              <p className="text-sm text-gray-400 mb-2 line-clamp-2">{character.description}</p>
                            )}

                            <div className="flex flex-wrap gap-2 mb-2">
                              {character.aliases.map(alias => (
                                <span key={alias} className="px-2 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-xs">
                                  {alias}
                                </span>
                              ))}
                              {character.visual_traits.slice(0, 3).map(trait => (
                                <span key={trait} className="px-2 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-xs">
                                  {trait}
                                </span>
                              ))}
                              {character.visual_traits.length > 3 && (
                                <span className="px-2 py-0.5 rounded-full bg-dark-500 text-gray-400 text-xs">
                                  +{character.visual_traits.length - 3} more
                                </span>
                              )}
                            </div>

                            {/* Confidence bar */}
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-gray-500">Confidence:</span>
                              <div className="flex-1 max-w-24 h-1.5 bg-dark-500 rounded-full overflow-hidden">
                                <div
                                  className={`h-full ${getConfidenceColor(character.confidence)}`}
                                  style={{ width: `${character.confidence * 100}%` }}
                                />
                              </div>
                              <span className="text-xs text-gray-400">{Math.round(character.confidence * 100)}%</span>
                            </div>
                          </div>

                          {/* Actions */}
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => startEdit(character)}
                              className="p-2 rounded-lg hover:bg-dark-500 text-gray-400 hover:text-gray-200 transition-colors"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(character.id)}
                              className="p-2 rounded-lg hover:bg-dark-500 text-gray-400 hover:text-red-400 transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

