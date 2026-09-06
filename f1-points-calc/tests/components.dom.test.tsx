/** Component smoke tests for the shared UI primitives. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Button, { ButtonLink, buttonClasses } from '../src/components/ui/Button';
import SegmentedControl from '../src/components/ui/SegmentedControl';
import TeamColorStripe from '../src/components/common/TeamColorStripe';

describe('Button', () => {
  it('renders children and forwards clicks', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save grid</Button>);
    await userEvent.click(screen.getByRole('button', { name: 'Save grid' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('defaults to the secondary variant, size md', () => {
    render(<Button>Hi</Button>);
    const cls = screen.getByRole('button').className;
    expect(cls).toContain('bg-surface');
    expect(cls).toContain('px-3');
  });

  it('applies the primary variant and pressed state for toggles', () => {
    render(<Button variant="primary" pressed>Toggle</Button>);
    const btn = screen.getByRole('button');
    expect(btn.className).toContain('bg-carbon-800'); // pressed styling overrides variant fill
    expect(btn.getAttribute('aria-pressed')).toBe('true');
  });

  it('unpressed toggles omit aria-pressed entirely', () => {
    render(<Button>Plain</Button>);
    expect(screen.getByRole('button').getAttribute('aria-pressed')).toBeNull();
  });

  it('iconOnly variant uses the compact padding', () => {
    render(<Button iconOnly aria-label="Fullscreen">⛶</Button>);
    expect(screen.getByRole('button', { name: 'Fullscreen' }).className).toContain('p-2');
  });

  it('buttonClasses composes variant + size + custom className', () => {
    const cls = buttonClasses({ variant: 'danger', size: 'sm', className: 'extra' });
    expect(cls).toContain('hover:text-danger');
    expect(cls).toContain('px-2.5');
    expect(cls).toContain('extra');
  });
});

describe('ButtonLink', () => {
  it('renders an anchor with external-link attributes left to the caller', () => {
    render(
      <ButtonLink href="https://f1-track-metrics-lab.vercel.app" target="_blank" rel="noreferrer">
        Track Explorer
      </ButtonLink>
    );
    const link = screen.getByRole('link', { name: 'Track Explorer' });
    expect(link.getAttribute('href')).toBe('https://f1-track-metrics-lab.vercel.app');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noreferrer');
  });
});

describe('SegmentedControl', () => {
  const options = [
    { value: 'tables', label: 'Tables' },
    { value: 'charts', label: 'Charts' },
  ] as const;

  it('marks the active option with aria-selected and highlights it', () => {
    render(<SegmentedControl options={[...options]} value="charts" onChange={() => {}} aria-label="Standings view" />);
    const active = screen.getByRole('tab', { name: 'Charts' });
    const inactive = screen.getByRole('tab', { name: 'Tables' });
    expect(active.getAttribute('aria-selected')).toBe('true');
    expect(active.className).toContain('bg-surface');
    expect(inactive.getAttribute('aria-selected')).toBe('false');
  });

  it('fires onChange with the chosen value', async () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={[...options]} value="tables" onChange={onChange} />);
    await userEvent.click(screen.getByRole('tab', { name: 'Charts' }));
    expect(onChange).toHaveBeenCalledWith('charts');
  });
});

describe('TeamColorStripe', () => {
  it('renders a solid stripe for single-color teams', () => {
    const { container } = render(<TeamColorStripe team={{ color: '#ff8000' }} />);
    const stripe = container.firstElementChild as HTMLElement;
    expect(stripe.getAttribute('aria-hidden')).toBe('true');
    expect(stripe.style.background).toBe('rgb(255, 128, 0)');
    expect(stripe.style.position).toBe('absolute');
  });

  it('renders the two-tone gradient when a secondary color exists', () => {
    const { container } = render(
      <TeamColorStripe team={{ color: '#ff8000', secondaryColor: '#ffffff' }} widthPx={6} />
    );
    const stripe = container.firstElementChild as HTMLElement;
    expect(stripe.style.background).toContain('linear-gradient');
    expect(stripe.style.background).toContain('#ff8000');
    expect(stripe.style.background).toContain('#ffffff');
    expect(stripe.style.width).toBe('6px');
  });

  it('falls back to gray for a missing team', () => {
    const { container } = render(<TeamColorStripe team={null} />);
    expect((container.firstElementChild as HTMLElement).style.background).toBe('rgb(204, 204, 204)');
  });
});
