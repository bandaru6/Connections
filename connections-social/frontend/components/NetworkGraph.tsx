'use client'

import { useEffect, useRef } from 'react'
import { Network, DataSet } from 'vis-network/standalone'

interface Node {
  name: string
  is_unknown: boolean
}

interface Edge {
  source: string
  target: string
  weight: number
}

interface NetworkGraphProps {
  center: string
  nodes: Node[]
  edges: Edge[]
  onNodeClick?: (name: string) => void
}

export default function NetworkGraph({ center, nodes, edges, onNodeClick }: NetworkGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    // Create nodes dataset
    const nodesData = new DataSet(
      nodes.map((node, i) => ({
        id: node.name,
        label: node.name.length > 15 ? node.name.slice(0, 12) + '...' : node.name,
        title: node.name,
        color: node.name === center
          ? { background: '#3b82f6', border: '#2563eb' }
          : node.is_unknown
            ? { background: '#666', border: '#444' }
            : { background: '#22c55e', border: '#16a34a' },
        font: {
          color: '#fff',
          size: node.name === center ? 14 : 12,
        },
        size: node.name === center ? 25 : 18,
      }))
    )

    // Create edges dataset
    const edgesData = new DataSet(
      edges.map((edge, i) => ({
        id: i,
        from: edge.source,
        to: edge.target,
        value: edge.weight,
        title: `Weight: ${edge.weight}`,
        color: { color: '#555', highlight: '#3b82f6' },
      }))
    )

    // Network options
    const options = {
      nodes: {
        shape: 'dot',
        borderWidth: 2,
      },
      edges: {
        width: 1,
        scaling: {
          min: 1,
          max: 5,
        },
        smooth: {
          enabled: true,
          type: 'continuous',
          roundness: 0.5,
        },
      },
      physics: {
        enabled: true,
        barnesHut: {
          gravitationalConstant: -3000,
          springLength: 120,
          springConstant: 0.04,
        },
        stabilization: {
          iterations: 100,
        },
      },
      interaction: {
        hover: true,
        tooltipDelay: 100,
      },
    }

    // Create network
    const network = new Network(
      containerRef.current,
      { nodes: nodesData, edges: edgesData },
      options
    )

    // Handle node click
    network.on('click', (params) => {
      if (params.nodes.length > 0 && onNodeClick) {
        onNodeClick(params.nodes[0] as string)
      }
    })

    networkRef.current = network

    return () => {
      network.destroy()
    }
  }, [center, nodes, edges, onNodeClick])

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '350px',
        background: 'var(--bg-secondary)',
        borderRadius: '8px',
        border: '1px solid var(--border)',
      }}
    />
  )
}
