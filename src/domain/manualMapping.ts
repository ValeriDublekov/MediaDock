export interface ManualMapping {
  id: string;
  rawTitle: string;
  imdbId: string;
  createdAt: Date;
  parsedTitle: string | null;
  parsedYear: number | null;
  createdBy?: string | null;
}

export interface ManualMappingRepository {
  getManualMappings(): Promise<ManualMapping[]>;
  saveManualMapping(mapping: Omit<ManualMapping, 'createdAt'>): Promise<void>;
  deleteManualMapping(mappingId: string): Promise<void>;
}
