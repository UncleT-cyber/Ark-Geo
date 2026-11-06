content = open('src/components/workbench/ArkControl.tsx', 'r').read()

start_marker = '              <div className="ark-model-selector-compact">'
end_marker = '              </div>\n\n        {execution.lifecycle_status'

start_idx = content.find(start_marker)
if start_idx == -1:
    print("Could not find start marker")
else:
    end_idx = content.find(end_marker, start_idx)
    if end_idx == -1:
        print("Could not find end marker")
    else:
        end_idx += len(end_marker)

        new_block = '''              <div className="ark-model-selector-compact">
                <button type="button" className="ark-model-pill" onClick={() => setModelMenuOpen(!modelMenuOpen)} title={selectedModel || 'Select model'}>
                  <span className="ark-model-name">{selectedModel ? models.find(m => m.id === selectedModel)?.name || selectedModel : 'Select model'}</span>
                  <ChevronDown size={14} />
                </button>
                {modelsLoaded && modelMenuOpen && (
                  <div className="ark-model-popover">
                    <input type="text" className="ark-model-search" placeholder="Search models…" />
                    {Object.entries(providerGroups).map(([provider, models]) => (
                      <div key={provider} className="ark-model-group">
                        <div className="ark-model-group-label">{provider}</div>
                        {models.map(m => (
                          <button key={m.id} type="button" className={`ark-model-item ${m.id === selectedModel ? 'selected' : ''} ${!m.available ? 'disabled' : ''}`} onClick={() => {
                            setSelectedModel(m.id);
                            setModelMenuOpen(false);
                          }}>
                            <span className="ark-model-item-name">{m.name}</span>
                            <span className={`ark-model-status ${m.available ? 'available' : 'unavailable'}`}>{m.available ? 'Available' : 'Unavailable'}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>'''

        content = content[:start_idx] + new_block + content[end_idx:]
        open('src/components/workbench/ArkControl.tsx', 'w').write(content)
        print('Model selector popup updated successfully')
else:
    print('Could not find the model selector block')
