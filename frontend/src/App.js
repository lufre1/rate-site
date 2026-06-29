import React, { useState, useEffect } from 'react';

const API = 'http://localhost:8000';

function App() {
  const [menu, setMenu] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [mensas, setMensas] = useState([]);
  const [showReviews, setShowReviews] = useState({});

  useEffect(() => {
    fetch(`${API}/mensas`)
      .then(r => r.json())
      .then(m => setMensas(m))
      .catch(() => setMensas(['Zentralmensa', 'CGiN', 'Mensa am Turm', 'Bistro HAWK']));
  }, []);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/menu/${date}`)
      .then(r => r.json())
      .then(data => { setMenu(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, [date]);

  const filtered = filter === 'all' ? menu : menu.filter(m => m.mensa === filter);
  const grouped = {};
  filtered.forEach(m => {
    if (!grouped[m.mensa + m.type]) grouped[m.mensa + m.type] = [];
    grouped[m.mensa + m.type].push(m);
  });

  return (
    <div style={{ minHeight: '100vh', background: '#f0f2f5', fontFamily: '-apple-system, sans-serif' }}>
      <header style={{ background: 'linear-gradient(135deg, #1e40af, #3b82f6)', padding: '20px', textAlign: 'center' }}>
        <h1 style={{ margin: 0, color: '#fff', fontSize: '28px' }}>Mensa Rating</h1>
        <p style={{ margin: '4px 0 0', color: '#bfdbfe', fontSize: '14px' }}>Rate your canteen meals in Göttingen</p>
      </header>

      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '16px' }}>
        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap', justifyContent: 'center' }}>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '14px' }}
          />
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '14px' }}
          >
            <option value="all">All Mensas</option>
            {mensas.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>Loading...</div>
        ) : menu.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
            <p>No menu for this date. Try today or the next 7 days.</p>
          </div>
        ) : (
          Object.keys(grouped).sort().map(key => {
            const [mensa, type] = key.split('_TYPE_');
            const items = grouped[key];
            const typeLabels = { main: 'Main', side: 'Side', dessert: 'Dessert' };
            return (
              <>
                <h2 key={key} style={{ color: '#374151', fontSize: '18px', marginTop: 24, marginBottom: 8,
                  borderBottom: '3px solid #3b82f6', paddingBottom: 8 }}>
                  {mensa} &mdash; {typeLabels[type] || type}
                </h2>
                {items.map(meal => (
                  <DishCard key={meal.id} meal={meal} />
                ))}
              </>
            );
          })
        )}
      </div>
    </div>
  );
}

function DishCard({ meal }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [name, setName] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [reviews, setReviews] = useState([]);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (show && reviews.length === 0) {
      fetch(`${API}/ratings/${meal.id}`)
        .then(r => r.json())
        .then(data => setReviews(data))
        .catch(() => {});
    }
  }, [show, meal.id]);

  const submitRating = async () => {
    if (rating === 0) return;
    await fetch(`${API}/rate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meal_id: meal.id, rating, comment, user_name: name }),
    });
    setSubmitted(true);
    setTimeout(() => { setSubmitted(false); setRating(0); setComment(''); setName(''); setShow(true); }, 1500);
  };

  const typeColors = {
    vegan: { bg: '#dcfce7', color: '#166534' },
    vegetarian: { bg: '#fef9c3', color: '#854d0e' },
    dessert: { bg: '#fce7f3', color: '#9d174d' },
    main: { bg: '#e0e7ff', color: '#3730a3' },
    side: { bg: '#f3e8ff', color: '#6b21a8' },
  };
  const tc = typeColors[meal.type] || typeColors.main;

  return (
    <div style={{ background: '#fff', borderRadius: 10, border: '1px solid #e5e7eb',
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)', padding: '14px 16px', marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{ fontSize: '16px', fontWeight: 600, color: '#111827' }}>{meal.name}</span>
            <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: 4,
              background: tc.bg, color: tc.color, fontWeight: 500, textTransform: 'uppercase' }}>
              {meal.type}
            </span>
          </div>
          {meal.description && (
            <p style={{ margin: '4px 0', color: '#6b7280', fontSize: '13px' }}>
              {meal.description.replace(/, +/g, ', ')}
            </p>
          )}
        </div>
        <div style={{ textAlign: 'right', marginLeft: 12, whiteSpace: 'nowrap' }}>
          {meal.rating_count > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
              <span style={{ color: '#f59e0b', fontSize: '14px' }}>{'★'.repeat(Math.round(meal.avg_rating))}{'☆'.repeat(5 - Math.round(meal.avg_rating))}</span>
              <span style={{ color: '#6b7280', fontSize: '13px' }}>{meal.avg_rating} ({meal.rating_count})</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #f3f4f6' }}>
        {submitted ? (
          <p style={{ color: '#16a34a', fontSize: '13px', margin: 0 }}>Thank you for rating!</p>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
              {[1, 2, 3, 4, 5].map(i => (
                <button key={i} onClick={() => setRating(i)} style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: '22px', padding: 0, lineHeight: 1,
                  color: i <= rating ? '#f59e0b' : '#d1d5db'
                }}>â˜…</button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input placeholder="Your name (optional)" value={name}
                onChange={e => setName(e.target.value)}
                style={{ flex: 0, minWidth: 80, padding: '4px 8px', border: '1px solid #d1d5db',
                  borderRadius: 6, fontSize: '13px' }} />
              <textarea placeholder="Your thoughts..." value={comment}
                onChange={e => setComment(e.target.value)}
                rows={1}
                style={{ flex: 1, padding: '4px 8px', border: '1px solid #d1d5db',
                  borderRadius: 6, fontSize: '13px', resize: 'none' }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitRating(); } }} />
              <button
                onClick={submitRating}
                disabled={rating === 0}
                style={{
                  padding: '4px 12px', borderRadius: 6, border: 'none',
                  background: rating > 0 ? '#3b82f6' : '#d1d5db',
                  color: rating > 0 ? '#fff' : '#9ca3af',
                  cursor: rating > 0 ? 'pointer' : 'not-allowed',
                  fontSize: '13px', fontWeight: 500, whiteSpace: 'nowrap'
                }}>
                Rate
              </button>
            </div>
          </>
        )}

        {meal.rating_count > 0 && (
          <button onClick={() => setShow(!show)} style={{
            border: 'none', background: 'none', color: '#3b82f6',
            cursor: 'pointer', fontSize: '12px', padding: '6px 0 0', marginTop: 2
          }}>
            {show ? 'â–²' : 'â–¼'} {' '}Reviews ({meal.rating_count})
          </button>
        )}

        {show && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #f3f4f6' }}>
            {reviews.length === 0 ? (
              <p style={{ color: '#9ca3af', fontSize: '12px', margin: 0 }}>No reviews yet</p>
            ) : (
              reviews.map(r => (
                <div key={r.id} style={{ padding: '4px 0' }}>
                  <span style={{ color: '#6b7280', fontSize: '12px' }}>
                    {r.user_name || 'Anonymous'} &middot; {'â˜…'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}
                  </span>
                  {r.comment && (
                    <p style={{ margin: '2px 0 0', fontSize: '13px', color: '#374151' }}>{r.comment}</p>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
