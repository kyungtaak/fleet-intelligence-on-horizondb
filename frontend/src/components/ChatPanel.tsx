import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowRight,
  Bot,
  LocateFixed,
  RotateCcw,
  Send,
  UserRound,
} from 'lucide-react'
import type { SearchResponse, Shipment } from '../types'
import { StatusBadge } from './StatusBadge'

const SUGGESTIONS = [
  'Show medical supplies for clinics',
  'Find delayed electronics from Asia',
  'Which shipments are going to Europe?',
  'Show cold-chain food and medicine',
]

interface ChatMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  shipments?: Shipment[]
  chatModel?: string
}

interface ChatPanelProps {
  onSearch: (query: string) => Promise<SearchResponse>
  onLocate: (shipment: Shipment) => void
  onShowAll: () => void
}

const initialMessage: ChatMessage = {
  id: 1,
  role: 'assistant',
  text: 'Ask about cargo, routes, regions, or shipment status. I will rank the closest matches by cosine similarity.',
}

export function ChatPanel({ onSearch, onLocate, onShowAll }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage])
  const [input, setInput] = useState('')
  const [searching, setSearching] = useState(false)
  const messageEnd = useRef<HTMLDivElement>(null)
  const nextMessageId = useRef(2)

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, searching])

  async function submitQuery(query: string) {
    const normalized = query.trim()
    if (normalized.length < 2 || searching) return

    const userMessage: ChatMessage = {
      id: nextMessageId.current++,
      role: 'user',
      text: normalized,
    }
    setMessages((current) => [...current, userMessage])
    setInput('')
    setSearching(true)

    try {
      const result = await onSearch(normalized)
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId.current++,
          role: 'assistant',
          text: result.answer,
          shipments: result.shipments,
          chatModel: result.chat_model,
        },
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId.current++,
          role: 'assistant',
          text:
            error instanceof Error
              ? `Search failed: ${error.message}`
              : 'Search failed. Please try again.',
        },
      ])
    } finally {
      setSearching(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitQuery(input)
  }

  function resetChat() {
    setMessages([initialMessage])
    setInput('')
    onShowAll()
  }

  return (
    <aside className="chat-panel workspace-panel" aria-label="Semantic shipment search">
      <div className="panel-heading chat-heading">
        <div>
          <span className="eyebrow">Vector search</span>
          <h2>Shipment assistant</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="Reset conversation"
          aria-label="Reset conversation"
          onClick={resetChat}
        >
          <RotateCcw size={17} />
        </button>
      </div>

      <div className="chat-messages" aria-live="polite">
        {messages.map((message, messageIndex) => (
          <div className={`chat-turn ${message.role}`} key={message.id}>
            <span className="chat-avatar" aria-hidden="true">
              {message.role === 'assistant' ? (
                <Bot size={17} />
              ) : (
                <UserRound size={17} />
              )}
            </span>
            <div className="chat-turn-content">
              <p>{message.text}</p>
              {messageIndex === 0 ? (
                <div className="suggestion-list">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      onClick={() => void submitQuery(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}

              {message.shipments?.length ? (
                <div className="chat-results">
                  {message.shipments.map((shipment) => (
                    <article className="chat-result" key={shipment.id}>
                      <div className="chat-result-header">
                        <strong>{shipment.shipment_number}</strong>
                        <StatusBadge status={shipment.status} compact />
                      </div>
                      <b>{shipment.title}</b>
                      <p>{shipment.description}</p>
                      <div className="chat-result-route">
                        <span>{shipment.origin_name}</span>
                        <ArrowRight size={12} aria-hidden="true" />
                        <span>{shipment.destination_name}</span>
                      </div>
                      <div className="chat-result-footer">
                        <span>
                          {shipment.similarity !== null
                            ? `${Math.round(shipment.similarity * 100)}% similar`
                            : 'Semantic match'}
                        </span>
                        <button type="button" onClick={() => onLocate(shipment)}>
                          <LocateFixed size={14} />
                          Locate
                        </button>
                      </div>
                    </article>
                  ))}
                  <span className="query-engine">
                    {message.chatModel} · Agent Framework · DiskANN
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {searching ? (
          <div className="chat-turn assistant searching-turn">
            <span className="chat-avatar" aria-hidden="true">
              <Bot size={17} />
            </span>
            <div className="typing-indicator" aria-label="Searching">
              <span />
              <span />
              <span />
            </div>
          </div>
        ) : null}
        <div ref={messageEnd} />
      </div>

      <form className="chat-composer" onSubmit={handleSubmit}>
        <label>
          <span className="sr-only">Ask about shipments</span>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about shipments"
            maxLength={300}
            disabled={searching}
          />
        </label>
        <button
          type="submit"
          aria-label="Send message"
          title="Send"
          disabled={input.trim().length < 2 || searching}
        >
          <Send size={17} />
        </button>
      </form>
    </aside>
  )
}