import numpy as np
import scipy.linalg as la
from .bases import FourierBesselBasis
from .quad import boundary_nodes, cached_leggauss
from .utils import *
from functools import cache, lru_cache
from pygsvd import gsvd

class PolygonEVP:
    """Class for polygonal Dirichlet Laplacian eigenproblems
    Builds a Fouier-Bessel basis which is adapdated to the polygon with given
    vertices and number of expansion orders. Evaluates this basis on a set of

    """
    def __init__(self,vertices,orders,boundary_pts=20,interior_pts=50,
                 boundary_method='even',interior_method='random',
                 bdry_nodes=None,bdry_weights=None,int_nodes=None,int_weights=None):
        self.basis = FourierBesselBasis(vertices,orders)
        self.vertices = self.basis.vertices
        self.n_vert = self.basis.n_vert
        self.orders = self.basis.orders

        x_v,y_v = self.vertices.T
        # catch integer argument to construct boundary points
        if type(boundary_pts) is int:
            if np.sum(self.orders>0) == 1:
                idx = np.argwhere(self.orders>0)[0]
                skip = np.concatenate((idx-1,idx))
            else:
                skip = None
            if boundary_method == 'even':
                boundary_pts = boundary_points(x_v,y_v,boundary_pts,skip=skip)
            else:
                boundary_pts = boundary_nodes(vertices,boundary_pts,boundary_method,skip)[0]

        # process boundary_pts array to be of shape (m_b,2)
        self.boundary_pts = np.asarray(boundary_pts)
        if self.boundary_pts.shape[0] == 2:
            self.boundary_pts = self.boundary_pts.T
        if self.boundary_pts.shape[1] != 2 or self.boundary_pts.ndim != 2:
            print(self.boundary_pts.shape)
            raise ValueError('boundary_pts must be a 2-dimensional array '\
                             'of x & y coordinates')

        # catch integer argument to construct interior points
        if type(interior_pts) is int:
            if interior_method == 'random':
                interior_pts = interior_points(x_v,y_v,interior_pts)

        # process interior_pts array to be of shape (m_i,2)
        self.interior_pts = np.asarray(interior_pts)
        if self.interior_pts.shape[0] == 2:
            self.interior_pts = self.interior_pts.T
        if self.interior_pts.shape[1] != 2 or self.interior_pts.ndim != 2:
            raise ValueError('interior_pts must be a 2-dimensional array '\
                             'of x & y coordinates')

        # set default points for the basis to be boundary_pts and interior_pts
        x_b,y_b = self.boundary_pts.T
        x_i,y_i = self.interior_pts.T
        x = np.concatenate((x_b,x_i))
        y = np.concatenate((y_b,y_i))
        self.basis.set_default_points(x,y)

        # label interior points and which edges the boundary points lie on
        self.points = np.vstack((x,y)).T
        self.edge_idx = edge_indices(self.points,self.vertices)

        # default tolerance parameters
        self.rtol = 0
        self.mtol = 1e-4

        # nodes and weights for quadrature
        if bdry_nodes is not None:
            self.bdry_nodes = bdry_nodes
            self.bdry_weights = bdry_weights
            self.int_nodes = int_nodes
            self.int_weights = int_weights
            self.nodes = np.concatenate((bdry_nodes,int_nodes))
            quad_weights = np.concatenate((bdry_weights,int_weights))
            self.weights = np.sqrt(quad_weights)[:,np.newaxis]
            self.n_basis = FourierBesselBasis(vertices,orders)
            self.n_basis.set_default_points(*self.nodes.T)

        # area and perimiter
        self.area = polygon_area(*self.vertices.T)
        self.perimiter = polygon_perimiter(*self.vertices.T)

        # lower bound for first eigenvalue
        self.lambda_1_lb = 5.76*np.pi/self.area

        # eigenvalue array
        self._ordered_eigs = np.array([],dtype='float64')
        self._eigs = np.array([],dtype='float64')

    @property
    def ordered_eigs(self):
        return np.sort(self._ordered_eigs)

    @ordered_eigs.setter
    def ordered_eigs(self,arr):
        self._ordered_eigs = np.sort(arr)

    @property
    def eigs(self):
        return np.sort(self._eigs)

    @eigs.setter
    def eigs(self,arr):
        self._eigs = np.sort(arr)


    @cache
    def subspace_sines(self,lambda_,rtol=None,pivot=True):
        """Compute the sines of subspace angles, which are the singular values of Q_B(\lambda)"""
        if rtol is None: rtol = self.rtol
        A = self.basis(lambda_)
        m_b = self.boundary_pts.shape[0]
        if pivot:
            Q,R,_ = la.qr(A, mode='economic', pivoting=True)
            # drop columns of Q corresponding to small diagonal entries of R
            r = np.abs(np.diag(R))
            cutoff = (r>r[0]*rtol).sum()
        else:
            Q,R = la.qr(A, mode='economic')
            cutoff = Q.shape[1]

        # calculate singular values
        try:
            return la.svd(Q[:m_b,:cutoff],compute_uv=False)[::-1]
        except:
            raise ValueError(f'non-finite SVD for lam={lambda_}')

    @cache
    def weighted_subspace_sines(self,lambda_,rtol=None,pivot=True):
        """Compute the sines of subspace angles, which are the singular values of Q_B(\lambda)
        for the quadrature-weighted problem"""
        if rtol is None: rtol = self.rtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        if pivot:
            Q,R,_ = la.qr(A, mode='economic', pivoting=True)
            # drop columns of Q corresponding to small diagonal entries of R
            r = np.abs(np.diag(R))
            cutoff = (r>r[0]*rtol).sum()
        else:
            Q,R = la.qr(A, mode='economic')
            cutoff = Q.shape[1]

        # calculate singular values
        try:
            return la.svd(Q[:m_b,:cutoff],compute_uv=False)[::-1]
        except:
            raise ValueError(f'non-finite SVD for lam={lambda_}')

    @cache
    def gsvd_subspace_tans(self,lambda_):
        """Use GSVD to compute the tangents of the subspace angles"""
        if rtol is None: rtol = self.rtol
        A = self.basis(lambda_)
        m_b = self.boundary_pts.shape[0]
        C,S,_ = gsvd(A[:m_b],A[m_b:],extras='')
        return np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))[::-1]

    @cache
    def rgsvd_subspace_tans(self,lambda_,rtol=None):
        """Use regularized GSVD to compute the tangents of the subspace angles"""
        if rtol is None: rtol = self.rtol
        A = self.basis(lambda_)
        m_b = self.boundary_pts.shape[0]

        Q,R = la.qr(A, mode='economic')
        U,s,V = la.svd(R)
        cutoff = (s>rtol).sum()
        if cutoff == 0:
            cutoff = 1
        U1 = U[:,:cutoff]

        C,S,_ = gsvd(Q[:m_b]@U1,Q[m_b:]@U1,extras='')
        return np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))[::-1]

    @cache
    def gevd_subspace_tans(self,lambda_):
        """Use GEVD to compute the tangents of the subspace angles"""
        A = self.basis(lambda_)
        m_b = self.boundary_pts.shape[0]
        e = la.eigvals(A[:m_b].T@A[:m_b],A[m_b:].T@A[m_b:])
        return np.sort(np.sqrt(e.real))

    @cache
    def gsvd_weighted_subspace_tans(self,lambda_):
        """Computes the subspace angle tangents for the quadrature-weighted problem
        using the GSVD"""
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        C,S,_ = gsvd(A[:m_b],A[m_b:],extras='')
        return np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))[::-1]

    @cache
    def rgsvd_weighted_subspace_tans(self,lambda_,rtol=None):
        """Computes the subspace angle tangents for the quadrature-weighted problem
        using the regularized GSVD"""
        if rtol is None: rtol = self.rtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        Q,R = la.qr(A, mode='economic')
        U,s,V = la.svd(R)
        cutoff = (s>rtol).sum()
        if cutoff == 0:
            cutoff = 1
        U1 = U[:,:cutoff]

        C,S,_ = gsvd(Q[:m_b]@U1,Q[m_b:]@U1,extras='')
        return np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))[::-1]

    @cache
    def sigma(self,lambda_,rtol=None,pivot=True):
        """Compute the smallest singular value of Q_B(\lambda)"""
        if rtol is None: rtol = self.rtol
        s = self.subspace_sines(lambda_,rtol,pivot)
        return s[0]

    @cache
    def gsigma(self,lambda_):
        """Compute the smallest generalized singular value of the pencil {A_B,A_I}"""
        s = self.gsvd_subspace_tans(lambda_)
        return s[0]

    @cache
    def rgsigma(self,lambda_,rtol=None):
        """Compute the smallest generalized singular value of the pencil {A_B,A_I}"""
        if rtol is None: rtol = self.rtol
        s = self.rgsvd_subspace_tans(lambda_,rtol=rtol)
        return s[0]

    @cache
    def gesigma(self,lambda_):
        """Compute the smallest generalized eigenvalue value of the pencil {(A_B^T)A_B,(A_I^T)A_I}"""
        s = self.gevd_subspace_tans(lambda_)
        return s[0]

    @lru_cache
    def eigenbasis(self,lambda_,rtol=None,mtol=None):
        """Returns a callable function which evaluates the approximate eigenbasis
        corresponding to lambda_"""
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        # get eigenbasis coefficient matrix
        C = self.eigenbasis_coef(lambda_,rtol,mtol)

        # return callable function of x,y from the basis
        def func(x,y):
            shape = np.asarray(x).shape
            shape = (*shape,C.shape[1])
            return (self.basis(lambda_,x,y)@C).reshape(shape)
        return func

    @lru_cache
    def eigenbasis_unweighted_coef(self,lambda_,rtol=None,mtol=None):
        """Returns the coefficients of an eigenbasis derived without quadrature weighting"""
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        A = self.basis(lambda_)
        m_b = len(self.boundary_pts)
        Q,R,P = la.qr(A, mode='economic', pivoting=True)
        Pinv = invert_permutation(P)

        # drop columns of Q corresponding to small diagonal entries of R
        r = np.abs(np.diag(R))
        cutoff = (r>r[0]*rtol).sum()

        # compute nullspace basis
        try:
            _,s,Vh = la.svd(Q[:m_b,:cutoff])
        except:
            raise ValueError('non-finite SVD')

        # determine multiplicity
        mult = (s<mtol).sum()
        if mult == 0:
            raise ValueError(f'lambda = {lambda_:.3e} has multiplicity zero (sigma = {s[-1]:.3e} > {mtol:.3e} = mtol)')

        # compute C
        C = np.zeros((A.shape[1],mult))
        C[:cutoff] = la.solve_triangular(R[:cutoff,:cutoff],Vh[-mult:].T)
        return C[Pinv]

    @lru_cache
    def eigenbasis_coef(self,lambda_,rtol=None,mtol=None):
        """Compute the coefficients of an eigenbasis, assuming lambda_ is an eigenvalue"""
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        Q,R,P = la.qr(A, mode='economic', pivoting=True)
        Pinv = invert_permutation(P)

        # drop columns of Q corresponding to small diagonal entries of R
        r = np.abs(np.diag(R))
        cutoff = (r>r[0]*rtol).sum()

        # compute nullspace basis
        try:
            _,s,Vh = la.svd(Q[:m_b,:cutoff])
        except:
            raise ValueError('non-finite SVD')

        # determine multiplicity
        mult = (s<mtol).sum()
        if mult == 0:
            raise ValueError(f'lambda = {lambda_:.3e} has multiplicity zero (sigma = {s[-1]:.3e} > {mtol} = mtol)')

        # compute C
        C = np.zeros((A.shape[1],mult))
        C[:cutoff] = la.solve_triangular(R[:cutoff,:cutoff],Vh[-mult:].T)
        return C[Pinv]

    @lru_cache
    def gsvd_eigenbasis_coef(self,lambda_,mtol=None):
        """Compute the coefficients of an eigenbasis, assuming lambda_ is an eigenvalue
        using the GSVD formulation"""
        if mtol is None: mtol = self.mtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        C,S,X = gsvd(A[:m_b],A[m_b:],extras='')
        s = np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))

        # determine multiplicity
        mult = (s<mtol).sum()
        if mult == 0:
            raise ValueError(f'lambda = {lambda_:.3e} has multiplicity zero (sigma = {s[-1]:.3e} > {mtol} = mtol)')

        # least squares solution for the right singular vectors
        return la.lstsq(X.T,np.eye(X.T.shape[0])[:,-mult:])[0]

    @lru_cache
    def rgsvd_eigenbasis_coef(self,lambda_,rtol=None,mtol=None):
        """Compute the coefficients of an eigenbasis, assuming lambda_ is an eigenvalue
        using the GSVD formulation with regularization"""
        raise NotImplementedError('rgsvd_eigenbasis_coef needs debugging')
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        Q,R = la.qr(A, mode='economic')
        U,s,V = la.svd(R)
        cutoff = (s>rtol).sum()
        if cutoff == 0:
            cutoff = 1
        U1 = U[:,:cutoff]

        C,S,X = gsvd(Q[:m_b]@U1,Q[m_b:]@U1,extras='')
        s = np.divide(C,S,out=np.full(C.shape,np.inf),where=(S!=0))

        # determine multiplicity
        mult = (s<mtol).sum()
        if mult == 0:
            raise ValueError(f'lambda = {lambda_:.3e} has multiplicity zero (sigma = {s[-1]:.3e} > {mtol} = mtol)')

        # least squares solution for the right singular vectors
        return la.lstsq(X.T,np.eye(X.T.shape[0])[:,-mult:])[0]

    @lru_cache
    def eigenbasis_node_eval(self,lambda_,rtol=None,mtol=None):
        """Evaluate the eigenbasis on the quadrature nodes, assuming lambda_
        is an eigenvalue"""
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        A = self.weights*self.n_basis(lambda_)
        m_b = len(self.bdry_nodes)
        Q,R,_ = la.qr(A, mode='economic', pivoting=True)

        # drop columns of Q corresponding to small diagonal entries of R
        r = np.abs(np.diag(R))
        cutoff = (r>r[0]*rtol).sum()

        # compute nullspace basis
        try:
            _,s,Vh = la.svd(Q[:m_b,:cutoff])
        except:
            raise ValueError('non-finite SVD')

        # determine multiplicity
        mult = (s<mtol).sum()
        if mult == 0:
            raise ValueError(f'lambda = {lambda_:.3e} has multiplicity zero (sigma = {s[-1]:.3e} > {mtol} = mtol)')

        return (Q[:,:cutoff]@(Vh[-mult:].T))/self.weights

    def eigenbasis_grad(self,lambda_,x,y,rtol=None,mtol=None):
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        # get eigenbasis coefficient matrix
        C = self.eigenbasis_coef(lambda_,rtol,mtol)

        # evaluate partial derivatives
        du_dx, du_dy = self.basis.grad(lambda_,x,y)

        return du_dx@C, du_dy@C

    @lru_cache
    def outward_normal_derivatives(self,lambda_,n=20,rtol=None,mtol=None):
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        # polygon vertices
        x_v,y_v = self.vertices.T

        # Gaussian quadrature nodes
        qnodes = cached_leggauss(n)[0]

        # transform nodes to boundary intervals
        slope_x, int_x = (np.roll(x_v,-1)-x_v)/2, (np.roll(x_v,-1)+x_v)/2
        slope_y, int_y = (np.roll(y_v,-1)-y_v)/2, (np.roll(y_v,-1)+y_v)/2
        x_b = qnodes[np.newaxis]*slope_x[:,np.newaxis] + int_x[:,np.newaxis]
        y_b = qnodes[np.newaxis]*slope_y[:,np.newaxis] + int_y[:,np.newaxis]

        # get basis gradients & reshape
        du_dx, du_dy = self.eigenbasis_grad(lambda_,x_b,y_b,rtol,mtol)
        du_dx = du_dx.reshape((self.n_vert,-1,du_dx.shape[1]))
        du_dy = du_dy.reshape((self.n_vert,-1,du_dy.shape[1]))

        # compute outward normal derivatives
        n = calc_normals(x_v,y_v).T[:,:,np.newaxis]
        return n[:,:1]*du_dx + n[:,1:]*du_dy

    @lru_cache
    def _gram_tensors(self,lambda_,n=20,rtol=None,mtol=None):
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        # polygon vertices
        x_v,y_v = self.vertices.T

        # Gaussian quadrature nodes & weights
        qnodes, qweights = cached_leggauss(n)

        # outward normal derivatives
        du_dn = self.outward_normal_derivatives(lambda_,n,rtol,mtol)

        # get edge lengths & weighting arrays
        d = calc_dists(x_v,y_v)[1][:,np.newaxis]
        f = ((d/2)*(qnodes+1)[np.newaxis])[:,:,np.newaxis]
        g = f[:,::-1]

        # compute integrals with quadrature
        I = (du_dn.transpose((0,2,1))@(du_dn*f*qweights[:,np.newaxis]))/(2*d[:,np.newaxis])
        J = (du_dn.transpose((0,2,1))@(du_dn*g*qweights[:,np.newaxis]))/(2*d[:,np.newaxis])

        # get X and Y gram tensors
        dx = np.roll(x_v,-1)-x_v
        dy = np.roll(y_v,-1)-y_v
        X = -np.roll(dy,1)*np.roll(I,1,axis=0).T - dy*J.T
        Y = np.roll(dx,1)*np.roll(I,1,axis=0).T + dx*J.T
        return X,Y

    def dlambda(self,lambda_,dx=None,dy=None,n=20,rtol=None,mtol=None):
        if rtol is None: rtol = self.rtol
        if mtol is None: mtol = self.mtol
        # catch direction derivative input errors
        if (dx is None) != (dy is None):
            raise ValueError('dx and dy must both be set, or left unset')
        elif dx is not None:
            dx,dy = np.asarray(dx),np.asarray(dy)
            if (dx.shape[0] != self.n_vert) or (dy.shape[0] != self.n_vert):
                raise ValueError(f'dx and dy must both be length {self.n_vert}')

        # compute multiplicity
        _,mult = self.sigma(lambda_,rtol,btol,mult_check=True)

        # catch repeated eigs
        if (mult > 1) and (dx is None):
            raise ValueError(f'Repeated eigenvalues only have a directional derivative (mult = {mult})')

        # compute gram tensors
        X,Y = self._gram_tensors(lambda_,n,rtol,mtol)

        # catch multiplicity mismatch
        if X.shape[1] != mult:
            raise ValueError(f'Multiplicity mismatch: {mult} != {X.shape[1]}')

        if dx is None: # simple eigenvalue gradient
            return X.flatten(), Y.flatten()
        else: # directional derivative
            M = (X@dx)+(Y@dy)
            if mult==1: # simple eigenvalue
                return M[0,0]
            else: # repeated eigenvalue
                return la.eigh(M,eigvals_only=True)

    def solve_ordered_eigs(self,k,xtol=1e-8,ytol=1e-5,verbose=False):
        """Finds the first k eigenvalues of the eigenvalue problem"""
        def obj(x):
            # subspace angle tangents
            sines = self.subspace_sines(x)[:2]
            return sines/np.sqrt(1-sines**2)
        # obj = lambda x: evp.subspace_sines(x)[:2]

        fevals = 0
        i = 0
        extend=False
        while len(self.ordered_eigs)<k:
            # get length of current array of eigenvalues
            k_current = len(self.ordered_eigs)
            if verbose: print(f'# of eigs found: {k_current}')

            # set starting point
            if extend: pass
            elif k_current == 0: start = self.lambda_1_lb
            else: start = self.ordered_eigs[k_current-1]

            # search up to Weyl asymptotic guess
            if not extend:
                end = self.weyl_k(k_current+1)
                lev = 1

                # search higher if asymptotics are off
                while end+1e8*xtol < start:
                    lev += 1
                    end = self.weyl_k(k_current+lev)

            # stepsizing
            n_pts = 20*lev
            h = (end-start)/n_pts

            # minsearch over [start,end]
            # add ghost points if needed
            if k_current != 0: start -= h
            minima, fe = minsearch(obj,start,end+h,h,xtol=xtol,verbose=verbose)
            fevals += fe
            for x_min in minima:
                print(x_min)
                if verbose: print(f"x_min={x_min:.3e},f(x_min)={obj(x_min)[0]:.3e}")
                mult = (self.subspace_sines(x_min)<ytol).sum()
                is_duplicate = False
                if len(self.ordered_eigs) > 0:
                    is_duplicate = (np.abs(x_min-self.ordered_eigs).min()<xtol)
                if verbose: print(f'mult={mult}, dup={is_duplicate}')
                if not is_duplicate and mult>0:
                    self.ordered_eigs = np.concatenate((self.ordered_eigs,mult*[x_min]))
                    if verbose: print(self.ordered_eigs)
                    if len(self.ordered_eigs)>=k:
                        break
            # check if no eigenvalue found
            if len(self.ordered_eigs) == k_current:
                if verbose: print('no eigenvalue found this step, extending search')
                gap = end-start
                start = end
                end = start+gap
                extend = True
            else:
                extend = False
        return self.ordered_eigs, fevals

    def sigma_min(self,a,b,ppl=10,tol=1e-8):
        if a < self.lambda_1_lb: a = self.lambda_1_lb
        spacing = (4*np.pi)/polygon_area(*self.vertices.T)
        s2tol = spacing/(3*ppl)
        n_samp = max(int(ppl*(b-a)/spacing+1),5)
        lambda_ = np.linspace(a,b,n_samp)
        angles = np.array([self.subspace_sines(lam)[-2:][::-1] for lam in lambda_])
        sigma_min_idx = np.where((angles[1:-1,0]<angles[:-2,0])&(angles[1:-1,0]<angles[2:,0]))[0]+1
        sigma2_tol_idx = np.where(angles[:,1]<s2tol)[0]

        minima = np.array([],dtype='float')
        for idx in sigma_min_idx:
            if (lambda_[idx+1]-lambda_[idx-1]) < 2*tol:
                minima = np.concatenate((minima,[lambda_[idx]]))
            elif idx in sigma2_tol_idx:
                lower = max(0,idx-2)
                upper = min(len(lambda_)-1,idx+2)
                minima = np.concatenate((minima,self.sigma_min(lambda_[lower],lambda_[upper],ppl=10*ppl)))
            else:
                minima = np.concatenate((minima,[golden_search(self.sigma,lambda_[idx-1],lambda_[idx+1],tol=tol)]))
        return np.unique(minima)

    def weyl_k(self,k):
        A = self.area
        P = self.perimiter
        return ((P+np.sqrt(P**2+16*np.pi*A*k))/(2*A))**2

    def plot_sigma(self,low,high,nlam,ax=None,**kwargs):
        if low < 1e-16 : low = 1e-16
        L = np.linspace(low,high,nlam+1)
        sigma = []
        for lam in L:
            sigma.append(self.sigma(lam))
        if ax is None:
            fig = plt.figure()
            plt.plot(L,sigma,**kwargs)
        else:
            ax.plot(L,sigma,**kwargs)

    def plot_gsigma(self,low,high,nlam,ax=None,**kwargs):
        if low < 1e-16 : low = 1e-16
        L = np.linspace(low,high,nlam+1)
        gsigma = []
        for lam in L:
            gsigma.append(self.gsigma(lam))
        if ax is None:
            fig = plt.figure()
            plt.plot(L,gsigma,**kwargs)
        else:
            ax.plot(L,gsigma,**kwargs)

    def plot_rgsigma(self,low,high,nlam,ax=None,tol=1e-14,**kwargs):
        if low < 1e-16 : low = 1e-16
        L = np.linspace(low,high,nlam+1)
        rgsigma = []
        for lam in L:
            rgsigma.append(self.rgsigma(lam,tol=tol))
        if ax is None:
            fig = plt.figure()
            plt.plot(L,rgsigma,**kwargs)
        else:
            ax.plot(L,rgsigma,**kwargs)

    def plot_gesigma(self,low,high,nlam,ax=None,**kwargs):
        if low < 1e-16 : low = 1e-16
        L = np.linspace(low,high,nlam+1)
        gesigma = []
        for lam in L:
            gesigma.append(self.gesigma(lam))
        if ax is None:
            fig = plt.figure()
            plt.plot(L,gesigma,**kwargs)
        else:
            ax.plot(L,gesigma,**kwargs)


# for compatability
PolygonEP = PolygonEVP
